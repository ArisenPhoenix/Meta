# from Meta import SchemaValidator
from Meta.meta_core import META_TYPES, MetaNodeMixin, wrap_meta_structure
from Meta.schema_validator import NoOpValidator, SchemaValidator
from Meta.helpers import is_key_instance_of_type
import types
from Meta.schema import Schema, fill_missing_keys
from Meta.helpers import get_default_from_type
from typing import Any, Dict, List, Set, Union, Tuple, get_args, get_origin, Optional, get_type_hints, TypeVar
from Meta.helpers import coerce_dict_keys
from helpers import coerce_keys_recursively, normalize_data

T = TypeVar("T", bound=MetaNodeMixin)

def is_instance_of_union(value, union_type):
    origin = get_origin(union_type)
    if origin is Union:
        return any(isinstance(value, t) for t in get_args(union_type))
    return False

 
class Meta:
    def __new__(cls, data: META_TYPES, schema: Any = None, **kwargs) -> META_TYPES:
        kwargs = kwargs if kwargs else {}
        schema_obj = schema if isinstance(schema, Schema) else Schema(schema, **kwargs)

        if kwargs.get("additional"):
            schema_obj = Schema(Meta._merge_additional_schema(schema_obj.schema, kwargs["additional"]), **kwargs)

        fill_defaults = kwargs.get("fill_defaults")
        if fill_defaults and isinstance(data, dict) and isinstance(schema_obj.schema, dict):
            fill_missing_keys(data, schema_obj.schema)

        data = normalize_data(data, schema_obj.schema)

        try:
            wrapped = wrap_meta_structure(data, schema=schema_obj, **kwargs)
        except Exception as e:
            print(str(e))
            print("DATA: ", data)
            print("SCHEMA: ", schema_obj.schema)
            exit(0)
        cls.schema = schema_obj



        return wrapped

    @staticmethod
    def convert_from_optional(tp):
        if tp is None:
            return type(None)
        if get_origin(tp) is Union and type(None) in get_args(tp):
            return tp  # Already correct
        return tp

    @staticmethod
    def convert_from_typed_dict_strict(td_cls):
        if not hasattr(td_cls, '__annotations__'):
            raise TypeError(f"{td_cls} is not a TypedDict")

        annotations = {}
        for base in reversed(td_cls.__mro__):
            if base is not object and hasattr(base, '__annotations__'):
                annotations.update(get_type_hints(base))

        return annotations

    @staticmethod
    def deduce_schema(data: Any, additional: Any = None) -> Any:
        def _deduce(value):
            # --- None → type(None) ---
            if value is None:
                return type(None)

            # --- Dict detection ---
            if isinstance(value, dict):
                if not value:
                    return Dict[Any, Any]

                key_types = {type(k) for k in value}
                val_types = {_deduce(v) for v in value.values()}

                key_type = key_types.pop() if len(key_types) == 1 else Union[key_types]
                val_type = val_types.pop() if len(val_types) == 1 else Union[val_types]
                return Dict[key_type, val_type]

            # --- List detection ---
            if isinstance(value, list):
                if not value:
                    return List[Any]
                item_types = {_deduce(v) for v in value}
                return List[item_types.pop()] if len(item_types) == 1 else List[Union[tuple(item_types)]]

            # --- Set detection ---
            if isinstance(value, set):
                if not value:
                    return Set[Any]
                item_types = {_deduce(v) for v in value}
                return Set[item_types.pop()] if len(item_types) == 1 else Set[Union[tuple(item_types)]]

            # --- Tuple detection ---
            if isinstance(value, tuple):
                if not value:
                    return Tuple[()]
                return Tuple[tuple(_deduce(v) for v in value)]

            # --- Fallback for scalar types ---
            return type(value)

        def _merge_schema(a: Any, b: Any) -> Any:
            if a == b:
                return a

            origin_a = get_origin(a)
            origin_b = get_origin(b)

            # --- Merge Dict[K, V] ---
            if origin_a == dict and origin_b == dict:
                k1, v1 = get_args(a)
                k2, v2 = get_args(b)

                merged_k = _merge_schema(k1, k2)
                merged_v = _merge_schema(v1, v2)
                return Dict[merged_k, merged_v]

            # --- Merge Union types ---
            if origin_a == Union or origin_b == Union:
                args_a = set(get_args(a)) if origin_a == Union else {a}
                args_b = set(get_args(b)) if origin_b == Union else {b}
                return Union[tuple(args_a | args_b)]

            return Union[a, b] if a != b else a

        def _merge_nested_schema(a: Any, b: Any) -> Any:
            if isinstance(a, dict) and isinstance(b, dict):
                keys = set(a) | set(b)
                return {
                    key: _merge_nested_schema(a.get(key), b.get(key)) if key in a and key in b else a.get(key,
                                                                                                          b.get(key))
                    for key in keys
                }

            return _merge_schema(a, b)

        # --- Step 1: infer schema from data ---
        inferred = _deduce(data)

        # --- Step 2: merge in additional schema info ---
        if additional:
            if isinstance(inferred, dict) and isinstance(additional, dict):
                inferred = _merge_nested_schema(inferred, additional)
            elif get_origin(inferred) is dict:
                k_type, v_type = get_args(inferred)
                add_v = _deduce(additional)
                inferred = Dict[k_type, _merge_schema(v_type, add_v)]

        return inferred

    @staticmethod
    def _merge_additional_schema(base: Any, additional: Any) -> Any:
        def _merge(a, b):
            # --- Match ---
            if a == b:
                return a

            origin_a = get_origin(a)
            origin_b = get_origin(b)

            # --- Merge Dict[T, V] + Dict[T, V] ---
            if origin_a == dict and origin_b == dict:
                k1, v1 = get_args(a)
                k2, v2 = get_args(b)
                merged_k = _merge(k1, k2)
                merged_v = _merge(v1, v2)
                return Dict[merged_k, merged_v]

            # --- Merge TypedDict-like dicts (explicit fields) ---
            if isinstance(a, dict) and isinstance(b, dict):
                out = dict(a)  # start with all of base
                for k, v in b.items():
                    if k in out:
                        out[k] = _merge(out[k], v)
                    else:
                        out[k] = v
                return out

            # --- Merge List, Set, Tuple ---
            if origin_a in (list, List) and origin_b in (list, List):
                (item_a,) = get_args(a) or (Any,)
                (item_b,) = get_args(b) or (Any,)
                return List[_merge(item_a, item_b)]

            if origin_a in (set, Set) and origin_b in (set, Set):
                (item_a,) = get_args(a) or (Any,)
                (item_b,) = get_args(b) or (Any,)
                return Set[_merge(item_a, item_b)]

            if origin_a in (tuple, Tuple) and origin_b in (tuple, Tuple):
                args_a = get_args(a)
                args_b = get_args(b)
                if args_a[-1:] == (Ellipsis,) and args_b[-1:] == (Ellipsis,):
                    return Tuple[_merge(args_a[0], args_b[0]), ...]
                if len(args_a) == len(args_b):
                    return Tuple[tuple(_merge(x, y) for x, y in zip(args_a, args_b))]
                return Union[a, b]  # fallback

            # --- Do NOT use Union for dicts with structural overlap ---
            return Union[a, b] if a != b else a

        return _merge(base, additional)

    @staticmethod
    def from_data(data: Any, **kwargs):
        schema = Meta.deduce_schema(data)
        return Meta(data, schema, **kwargs)

    # stubs for supporting the class API, for proper clarity
    def get(self, key: Any, default: Optional[Any] = None) -> Union[MetaNodeMixin, Any]:
        ...

    def add(self, *args: Any, **kwargs: Any) -> Union["Meta", MetaNodeMixin]:
        ...

    def set(self, *args: Any, **kwargs: Any) -> "Meta":
        ...

    def remove(self, key: Any) -> "Meta":
        ...

    def pop(self, key: Any) -> Union[MetaNodeMixin, Any, None]:
        ...

    def to_native(self) -> Any:
        ...

    def to_json(self) -> Any:
        ...

    def validate(self) -> None:
        ...

    def has(self, key_or_value: Any) -> bool:
        ...

    def __setitem__(self, key, value):
        ...




