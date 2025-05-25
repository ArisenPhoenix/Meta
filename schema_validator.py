from typing import Any, get_origin, get_args, Union, Dict
from Meta.helpers import (is_type_match, resolve_schema_key, validate_container_origins,
                          validate_dict, validate_list, validate_set)
import types

try:
    from types import UnionType
except ImportError:
    UnionType = None

def is_union(tp):
    origin = get_origin(tp)
    return origin is Union or origin is types.UnionType

class NoOpValidator:
    def validate_all(self, data): pass
    def validate(self, *args, **kwargs): pass
    def type_check(self, *args, **kwargs): pass
    def validate_flat(self, *args, **kwargs): pass
    # def __call__(self): pass

class SchemaValidator:
    def __init__(self, schema, MetaNode_mixin=None, **kwargs):
        self.schema = schema
        if MetaNode_mixin is None:
            from Meta.meta_base import MetaNodeMixin as MetaNode_mixin
        self.MetaNodeMixin = MetaNode_mixin
        self.strict = kwargs.get("strict", False)

    def _validate_native(self, data, expected_type, path="value"):
        if is_union(expected_type):
            expected_type = self.resolve_union_branch(data, expected_type)

        origin = get_origin(expected_type)

        if origin is dict:
            key_type, val_type = get_args(expected_type)
            try:
                for k, v in data.items():
                    self.type_check(k, key_type, f"{path}.key")
                    self._validate_native(v, val_type, f"{path}.{k}")
            except AttributeError as e:
                msg = f"{str(e)}\nOrigin: {origin}\nExpectedType: {expected_type}\nData: {data}"
                raise AttributeError(msg)

        elif origin in (list, set):
            (item_type,) = get_args(expected_type)
            for i, item in enumerate(data):
                self._validate_native(item, item_type, f"{path}[{i}]")

        else:
            self.type_check(data, expected_type, path)

    def _validate_meta(self, meta, expected_type):
        self.validate_recursive("value", meta, expected_type)

    def _extract_keyval_types(self, expected_type):
        origin = get_origin(expected_type)
        args = get_args(expected_type)

        if origin is dict and len(args) == 2:
            return args

        elif origin is Union:
            for sub_type in args:
                if get_origin(sub_type) is dict:
                    sub_args = get_args(sub_type)
                    if len(sub_args) == 2:
                        return sub_args
        return None, None

    def type_check(self, value: Any, expected_type: Any, key_path: str = None):
        if expected_type is None or expected_type is Any:
            return

        if isinstance(value, self.MetaNodeMixin):
            value = value.to_native()

        # ✅ Handle normalized Union as a tuple of types
        if isinstance(expected_type, tuple):
            if not any(isinstance(value, typ) for typ in expected_type):
                raise TypeError(f"[❌] {key_path}: expected one of {expected_type}, got {type(value)} → {value}")
            return

        # ✅ Handle normalized set of a single allowed type
        if isinstance(expected_type, set) and len(expected_type) == 1:
            inner_type = next(iter(expected_type))
            if not isinstance(value, set):
                raise TypeError(f"[❌] {key_path}: expected a set, got {type(value)}")
            for item in value:
                self.type_check(item, inner_type, key_path)
            return

        # ✅ Handle normalized list
        if isinstance(expected_type, list) and len(expected_type) == 1:
            inner_type = expected_type[0]
            if not isinstance(value, list):
                raise TypeError(f"[❌] {key_path}: expected a list, got {type(value)}")
            for i, item in enumerate(value):
                self.type_check(item, inner_type, f"{key_path}[{i}]")
            return

        # ✅ Handle normalized dict
        if isinstance(expected_type, dict) and len(expected_type) == 1:
            key_type, val_type = next(iter(expected_type.items()))
            if not isinstance(value, dict):
                raise TypeError(f"[❌] {key_path}: expected a dict, got {type(value)}")
            for k, v in value.items():
                self.type_check(k, key_type if not isinstance(key_type, tuple) else key_type, f"{key_path}.key")
                self.type_check(v, val_type, f"{key_path}.{k}")
            return

        # ✅ Handle direct scalar types
        if not is_type_match(value, expected_type, self.MetaNodeMixin):
            raise TypeError(f"[❌] {key_path}: expected {expected_type}, got {type(value)} → {value}")

    def validate(self, key, value):
        if self.schema is None:
            return

        expected_type = None

        # 1. Direct key match (exact key like "Title")
        if isinstance(self.schema, dict) and key in self.schema:
            expected_type = self.schema[key]

        # 2. Fallback match (key type like str, int)
        elif isinstance(self.schema, dict):
            for key_type, value_type in self.schema.items():
                if isinstance(key_type, type) and isinstance(key, key_type):
                    expected_type = value_type
                    break

        # 3. Fail if no matching schema type found
        if expected_type is None:
            raise TypeError(f"Key '{key}' not allowed by schema")

        # 4. Validate the value recursively (basic check here)
        if expected_type is not Any:
            origin = get_origin(expected_type)

            # --- Dict[KT, VT]
            if origin is dict:
                if not isinstance(value, dict):
                    raise TypeError(f"Key '{key}' expects a dict")
                key_type, val_type = get_args(expected_type)
                for k, v in value.items():
                    if not isinstance(k, key_type):
                        raise TypeError(f"Key '{k}' in '{key}' must be {key_type}")
                    if not isinstance(v, val_type):
                        raise TypeError(f"Value '{v}' in '{key}' must be {val_type}")

            elif not isinstance(value, expected_type):
                raise TypeError(f"Key '{key}' expects {expected_type}, got {type(value)}")

    # In SchemaValidator
    def validate_flat(self, key, value) -> Any:
        expected_type = self.schema_for(key)
        self.type_check(value, expected_type, key)
        return expected_type  # <- return the resolved type

    def resolve_union_branch(self, value, union_type):
        if not is_union(union_type):
            return union_type

        for arg in get_args(union_type):
            try:
                # Special case: allow empty containers to match their container type
                origin = get_origin(arg)

                if origin is dict and isinstance(value, dict) and not value:
                    return arg  # accept empty dict for Dict

                if origin is list and isinstance(value, list) and not value:
                    return arg

                if origin is set and isinstance(value, set) and not value:
                    return arg

                # Otherwise validate normally
                # self.type_check(value, arg)
                for curr_arg in get_args(union_type):
                    try:
                        SchemaValidator(curr_arg, self.MetaNodeMixin).validate_all(value)
                        return curr_arg
                    except TypeError:
                        continue
                # Otherwise validate normally
                self.type_check(value, arg)

            except TypeError:
                continue
        for arg in get_args(union_type):
            try:
                # Handle empty container matches
                origin = get_origin(arg)
                if origin is dict and isinstance(value, dict) and not value:
                    return arg
                if origin is list and isinstance(value, list) and not value:
                    return arg
                if origin is set and isinstance(value, set) and not value:
                    return arg

                # Strict validation attempt
                SchemaValidator(arg, self.MetaNodeMixin).validate_all(value)
                return arg

            except TypeError:
                continue

        raise TypeError(f"[❌] {value!r} did not match any Union types: {union_type}")

    def validate_tuple(self, key_path, value, expected_type):
        if not isinstance(value, tuple):
            raise TypeError(f"{key_path}: expected tuple, got {type(value)}")

        args = get_args(expected_type)
        if args and args[-1] is Ellipsis:
            subtype = args[0]
            for i, item in enumerate(value):
                self.validate_recursive(f"{key_path}[{i}]", item, expected_type=subtype)
        else:
            if len(args) != len(value):
                raise TypeError(f"{key_path}: expected {len(args)} elements, got {len(value)}")
            for i, (item, subtype) in enumerate(zip(value, args)):
                self.validate_recursive(f"{key_path}[{i}]", item, expected_type=subtype)

    def validate_container(self, key_path, value, expected_type):
        if expected_type is None:
            return None

        # unwrapped = value.to_native() if isinstance(value, self.MetaNodeMixin) else value
        self.type_check(value, expected_type, key_path)

        origin = get_origin(expected_type)

        if origin is list or origin is tuple:
            (item_type,) = get_args(expected_type)
            for i, item in enumerate(value):
                self.validate_recursive(f"{key_path}[{i}]", item, expected_type=item_type)

        elif origin is set:
            (item_type,) = get_args(expected_type)
            for item in value:
                self.validate_recursive(f"{key_path}{{{item}}}", item, expected_type=item_type)

        elif origin is dict:
            key_type, val_type = self._extract_keyval_types(expected_type)
            for k, v in value.items():
                self.validate_recursive(f"{key_path}.key", k, expected_type=key_type)
                self.validate_recursive(f"{key_path}.{k}", v, expected_type=val_type)


        return expected_type  # ✅ Add this

    def validate_scalar(self, key_path, value, expected_type):
        matched_type = self.resolve_union_branch(value, expected_type) if is_union(expected_type) else expected_type
        self.type_check(value, matched_type, key_path)
        return matched_type  # ✅ Add this


    def validate_recursive(self, key_path, value, expected_type=None):
        if expected_type is None:
            expected_type = resolve_schema_key(key_path, self.schema)

        origin = get_origin(expected_type)

        # ✅ Handle normalized or typing-based containers
        if origin in (list, set, dict) or isinstance(expected_type, (list, set, dict)):
            return self.validate_container(key_path, value, expected_type)

        if origin is tuple:
            return self.validate_tuple(key_path, value, expected_type)

        return self.validate_scalar(key_path, value, expected_type)

    def schema_for(self, key):
        if isinstance(self.schema, dict):
            # Direct match
            if key in self.schema:
                return self.schema[key]

            # Type match (including tuple of key types)
            for k_type, v_type in self.schema.items():
                if isinstance(k_type, tuple):
                    if any(isinstance(key, typ) for typ in k_type):
                        return v_type
                elif isinstance(k_type, type) and isinstance(key, k_type):
                    return v_type

        raise TypeError(f"[❌] Key '{key}' not allowed by schema")

    def validate_all(self, data):
        if self.schema is None:
            return

        expected_type = self.schema
        if isinstance(expected_type, dict) and isinstance(data, dict):
            for k in data:
                if k in expected_type:
                    continue
                matched = False
                for allowed_key_type in expected_type.keys():
                    if isinstance(allowed_key_type, tuple):
                        if any(isinstance(k, t) for t in allowed_key_type):
                            matched = True
                            break
                    elif isinstance(allowed_key_type, type):
                        if isinstance(k, allowed_key_type):
                            matched = True
                            break
                if not matched:
                    print("Failed with schema: ", self.schema)
                    raise TypeError(f"[❌] Key '{k}' not allowed by schema")

        # print(f"✅ [validate_all] Validating full structure against schema: {expected_type}")

        if isinstance(data, self.MetaNodeMixin):
            self._validate_meta(data, expected_type)
        else:
            self._validate_native(data, expected_type)

    def _validate_type(self, expected, value, path="root"):
        # Handle Union[...]
        origin = get_origin(expected)
        args = get_args(expected)

        # --- Any ---
        if expected is Any:
            return

        # --- Basic Type ---
        if isinstance(expected, type):
            if not isinstance(value, expected):
                raise TypeError(f"{path}: Expected {expected.__name__}, got {type(value).__name__} ({value})")
            return

        # --- Dict ---
        if validate_dict(expected, value, path, self._validate_type) is None:
            return

        # --- List ---
        if validate_list(expected, value, path, self._validate_type) is None:
            return

        # --- Set ---
        if validate_set(expected, value, path, self._validate_type) is None:
            return

        if validate_container_origins(origin, value, args, path, self._validate_type) is None:
            return

        # --- Fallback: hard fail ---
        raise TypeError(f"{path}: Unsupported schema type {expected}")











 # def validate_recursive(self, key_path, value, expected_type=None):
    #     if expected_type is None:
    #         expected_type = resolve_schema_key(key_path, self.schema)
    #
    #     origin = get_origin(expected_type)
    #     if origin in (list, set, dict):
    #         return self.validate_container(key_path, value, expected_type)
    #
    #     if origin is tuple:
    #         return self.validate_tuple(key_path, value, expected_type)
    #
    #     return self.validate_scalar(key_path, value, expected_type)






 # def schema_for(self, key):
    #     schema = self.schema
    #
    #     # 🔍 Support Union[dict, dict] or other combinations
    #     if is_union(schema):
    #         return self.resolve_union_branch_schema_for(key, schema)
    #
    #     # --- Dict[str, T] ---
    #     if isinstance(schema, dict):
    #         if key in schema:
    #             return schema[key]
    #         for k_type, v_type in schema.items():
    #             if isinstance(k_type, type) and isinstance(key, k_type):
    #                 return v_type
    #         raise TypeError(f"[❌] Key '{key}' is not allowed by schema {schema}")
    #
    #     origin = get_origin(schema)
    #     if origin in (dict, Dict):
    #         args = get_args(schema)
    #         return args[1] if len(args) == 2 else args[0]
    #
    #     raise TypeError(f"[❌] Schema does not support keys: {schema}")