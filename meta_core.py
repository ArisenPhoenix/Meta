# - Uses a shared `MetaNodeMixin`
# - Has a `META_METHODS` registry
# - Each Meta* type gets injected CRUD + to_json/to_native logic
# - Methods are chainable where appropriate

from typing import Any, Type, Union, get_origin, get_args, Iterable
from Meta.helpers import resolve_schema_key
from Meta.meta_base import MetaNodeMixin, MetaBool, MetaNone
from Meta.schema_validator import SchemaValidator, NoOpValidator
from Meta.schema import Schema
from Meta.helpers import coerce_dict_keys
from schema import fill_missing_keys


def get_default_value_from_type(tp: Any):
    if tp is Any or tp is None:
        return None

    origin = get_origin(tp)
    args = get_args(tp)

    if origin is Union:
        for sub in args:
            if sub is not type(None):
                return get_default_value_from_type(sub)
        return None

    if isinstance(tp, list):  # normalized list schema like [int]
        return []

    if isinstance(tp, set):  # normalized set schema like {str}
        return set()

    if isinstance(tp, dict):  # normalized dict schema like {int: str}
        return {}

    if tp in (str, int, float, bool):
        return tp()

    if origin in (list, set, dict):
        # Handle typing.List[int] etc.
        if origin is list:
            return []
        if origin is set:
            return set()
        if origin is dict:
            return {}

    if isinstance(tp, type):
        try:
            return tp()
        except Exception:
            return None

    return None


def create_meta_node_class(container_type: Type, name: str = None):
    if container_type is bool:
        return MetaBool

    name = name or f"Meta{container_type.__name__.capitalize()}"
    # --- Scalar Type (str, int, float) ---
    if container_type in (str, int, float, type(None)):
        class MetaScalar(container_type, MetaNodeMixin):
            def __new__(cls, value, schema=None, **kwargs):
                # instance = super().__new__(cls, value)
                # instance.schema = schema
                # instance.validator = SchemaValidator(schema, MetaNodeMixin)
                # instance.validator.type_check(value, schema, key_path=name)
                assert isinstance(schema, Schema), "Expected Schema instance"

                instance = super().__new__(cls, value)
                instance.schema = schema
                instance.validator = schema.build_validator()
                instance.validator.type_check(value, schema.schema, key_path=name)
                return instance

                # return instance

            def to_native(self): return container_type(self)

            def to_json(self): return container_type(self)

            def __repr__(self):
                return f"{container_type.__repr__(self)}"

        # Rename
        MetaScalar.__name__ = name
        MetaScalar.__qualname__ = name
        MetaScalar.__module__ = "__main__"
        return MetaScalar

    # --- Container Types ---
    name = name or f"Meta{container_type.__name__.capitalize()}"
    default_factory = dict if container_type is dict else list if container_type is list else set

    # --- Container Meta Class ---
    class MetaContainer(container_type, MetaNodeMixin):
        def __new__(cls, data=None, schema=None, **kwargs):
            assert isinstance(schema, Schema), "Expected Schema instance"


            # return instance
            if cls is MetaTuple:
                args = get_args(schema) if schema else ()
                if args and args[-1] is Ellipsis:
                    item_schema = args[0]
                    items = tuple(
                        wrap_meta_structure(i, schema=Schema.ensure(item_schema)) if not isinstance(i, MetaNodeMixin) else i
                        for i in (data or ())
                    )
                else:
                    items = tuple(
                        wrap_meta_structure(i, schema=Schema.ensure(s)) if not isinstance(i, MetaNodeMixin) else i
                        for i, s in zip((data or ()), args)
                    )
                instance = super().__new__(cls, items)
                instance.schema = schema
                instance.validator = schema.build_validator()
                return instance

            instance = super().__new__(cls)
            instance.schema = schema
            instance.validator = SchemaValidator(schema, MetaNodeMixin)
            return instance

        def __init__(self, data=None, schema=None, **kwargs):

            data = data if data is not None else default_factory()
            self.schema = schema
            # meta_type = META_TYPE_MAP[type(data)]
            self.validator = SchemaValidator(schema, MetaNodeMixin)
            if container_type is tuple:
                # All init work was already done in __new__
                return

            if isinstance(self, dict) and isinstance(data, dict):

                # data = coerce_dict_keys(data, schema)
                for k, v in data.items():
                    # k = self._coerce_key_type(k)
                    coerced_k = self._coerce_key_type(k)
                    resolved = Schema.ensure(self.resolve_schema(coerced_k, v))
                    if isinstance(v, dict) and isinstance(resolved, dict):
                        wrapped = wrap_meta_structure(v, schema=resolved)
                    else:
                        wrapped = v if isinstance(v, MetaNodeMixin) else wrap_meta_structure(v, schema=resolved)

                    self[coerced_k] = wrapped

            elif isinstance(self, list) and isinstance(data, list):
                for item in data:
                    resolved_schema = Schema.ensure(self.validator.validate_recursive(None, item) if self.validator else None)
                    wrapped = item if isinstance(item, MetaNodeMixin) else wrap_meta_structure(item, resolved_schema)
                    self.append(wrapped)

            elif isinstance(self, tuple) and isinstance(data, tuple):
                args = get_args(self.schema) if self.schema else ()
                if args and args[-1] is Ellipsis:
                    item_schema = args[0]
                    items = tuple(
                        wrap_meta_structure(i, schema=Schema.ensure(item_schema)) if not isinstance(i, MetaNodeMixin) else i
                        for i in data
                    )
                else:
                    items = tuple(
                        wrap_meta_structure(i, schema=Schema.ensure(s)) if not isinstance(i, MetaNodeMixin) else i
                        for i, s in zip(data, args)
                    )

                tmp = type(self)(items)
                self += tmp  # mutable hack – relies on `tuple` subclassing

            elif isinstance(self, set) and isinstance(data, set):
                for item in data:
                    resolved_schema = self.validator.validate_recursive(None, item) if self.validator else None
                    wrapped = item if isinstance(item, MetaNodeMixin) else wrap_meta_structure(item, Schema.ensure(resolved_schema))
                    self.add(wrapped)

            else:
                raise TypeError(f"Unsupported init for {type(self)} with data: {data}")

        def _coerce_key_type(self, key):
            if get_origin(self.schema) is dict:
                expected_key_type, _ = get_args(self.schema)
                if expected_key_type is int and isinstance(key, str) and key.isnumeric():
                    return int(key)
                elif expected_key_type is float and isinstance(key, str):
                    try:
                        return float(key)
                    except ValueError:
                        pass
                elif expected_key_type is bool and key in ("True", "False"):
                    return key == "True"
            return key

        # def resolve_schema(self, key, value):
        #     key = self._coerce_key_type(key)
        #
        #     if self.validator and isinstance(self.schema, dict):
        #         # --- Match exact key ---
        #         if key in self.schema:
        #             return self.schema[key]
        #
        #         # --- Match by key type (e.g., str, int) ---
        #         for k_type, v_type in self.schema.items():
        #             if isinstance(k_type, type) and isinstance(key, k_type):
        #                 return v_type
        #             if isinstance(k_type, tuple) and any(isinstance(key, t) for t in k_type):
        #                 return v_type
        #
        #     # --- Handle typing.Dict[str, T] form ---
        #     origin = get_origin(self.schema)
        #     if origin is dict:
        #         _, val_type = get_args(self.schema)
        #         return val_type
        #
        #     # --- Normalized schema form: {str: T} ---
        #     if isinstance(self.schema, dict):
        #         for k_type, v_type in self.schema.items():
        #             if isinstance(k_type, type) and isinstance(key, k_type):
        #                 return v_type
        #             if isinstance(k_type, tuple) and any(isinstance(key, t) for t in k_type):
        #                 return v_type
        #
        #     return None
        def resolve_schema(self, key, value):
            key = self._coerce_key_type(key)

            # ✅ Unwrap if self.schema is a Schema instance
            schema_base = self.schema.schema if isinstance(self.schema, Schema) else self.schema

            if self.validator and isinstance(schema_base, dict):
                # --- Match exact key ---
                if key in schema_base:
                    return schema_base[key]

                # --- Match by key type (e.g., str, int) ---
                for k_type, v_type in schema_base.items():
                    if isinstance(k_type, type) and isinstance(key, k_type):
                        return v_type
                    if isinstance(k_type, tuple) and any(isinstance(key, t) for t in k_type):
                        return v_type

            # --- typing.Dict[str, T] form ---
            origin = get_origin(schema_base)
            if origin is dict:
                _, val_type = get_args(schema_base)
                return val_type

            # --- Normalized schema form: {str: T} ---
            if isinstance(schema_base, dict):
                for k_type, v_type in schema_base.items():
                    if isinstance(k_type, type) and isinstance(key, k_type):
                        return v_type
                    if isinstance(k_type, tuple) and any(isinstance(key, t) for t in k_type):
                        return v_type

            return None

        @staticmethod
        def _unwrap(v):
            return v.to_native() if hasattr(v, "to_native") else v

        def _pull_args(self, *args):
            if not args:
                raise ValueError("No arguments supplied to add")

            if container_type is set:
                # Always treat the first arg as value; set.add(x)
                return None, args[0]

            if container_type is list:
                # list.add(x) or list.add(index, x)
                if len(args) == 1:
                    return None, args[0]
                elif len(args) == 2:
                    return args[0], args[1]
                else:
                    raise ValueError("Too many arguments for list.add()")

            if container_type is dict:
                if len(args) == 1 and isinstance(args[0], dict):
                    # for .update() etc
                    return args[0], None
                elif len(args) == 2:
                    return args[0], args[1]
                else:
                    raise ValueError("Invalid number of arguments for dict.add()")

            raise NotImplementedError(f"_pull_args not supported for {container_type}")

        # --- method overrides ---
        def add(self, *args, **kwargs):
            k, v = self._pull_args(*args)

            if container_type is dict:
                if isinstance(k, str) and k.isnumeric():
                    k = int(k)
                resolved = Schema.ensure(self.resolve_schema(k, v))
                val = wrap_meta_structure(v, resolved)
                dict.__setitem__(self, k, val)

            elif container_type is list:
                if len(args) == 1:
                    resolved = Schema.ensure(self.resolve_schema(k, v))
                    val = wrap_meta_structure(v, resolved)
                    # val = wrap_meta_structure(v, schema=self._infer_sub_schema())
                    list.append(self, val)

                elif len(args) == 2:
                    if isinstance(k, int):
                        # insert at index
                        resolved = Schema.ensure(self.resolve_schema(k, v))
                        val = wrap_meta_structure(v, resolved)
                        # val = wrap_meta_structure(v, schema=self._infer_sub_schema())
                        list.insert(self, k, val)


                    elif k is not None and k in self:
                        resolved = Schema.ensure(self.resolve_schema(k, v))
                        val = wrap_meta_structure(v, resolved)
                        existing = [i for i in self if self._unwrap(i) == self._unwrap(val)]
                        if not existing:
                            idx = next((i for i, item in enumerate(self) if self._unwrap(item) == self._unwrap(k)), None)
                            if idx is not None:
                                self.insert(idx, val)
                            # self[idx] = val

                    else:
                        resolved = Schema.ensure(self.resolve_schema(k, v))
                        val = wrap_meta_structure(v, resolved)
                        list.append(self, val)

                else:
                    raise ValueError("Invalid arguments for MetaList.add()")


            elif container_type is set:
                # k = args[0]
                val = args[0]

                if isinstance(val, Iterable) and not isinstance(val, (str, dict, MetaDict)):
                    for item in val:
                        resolved = self.resolve_schema(item, item)
                        wrapped = wrap_meta_structure(item, resolved)
                        set.add(self, wrapped)
                else:
                    resolved = self.resolve_schema(val, val)
                    wrapped = wrap_meta_structure(val, resolved)
                    set.add(self, wrapped)

            elif container_type is tuple:
                raise TypeError("Tuples are immutable; use .set(new_values) instead")


            else:
                raise NotImplementedError(f"Container type {container_type} cannot implement add")

            if isinstance(val, MetaNodeMixin) and isinstance(val, (dict, list, set)):
                return val  # Only return for chaining on containers
            return self
            # return self

        def remove(self, key):
            try:
                if container_type is dict:
                    dict.pop(self, key, None)
                elif container_type is list:
                    if isinstance(key, int):
                        list.pop(self, key)
                    else:
                        list.remove(self, key)
                elif container_type is set:
                    set.discard(self, key)
                elif container_type is tuple:
                    raise TypeError("Tuples are immutable; use .set(new_values) with modified values")

                else:
                    raise NotImplementedError()
            except Exception:
                pass
            return self

        def set(self, *args, **kwargs):

            if len(args) > 0:
                other, v = self._pull_args(*args)
                replace = kwargs.pop("replace", False)
                if len(args) == 1 and isinstance(other, dict):
                    if replace:
                        self.clear()
                    return self.update(other)

                elif len(args) == 2:
                    resolved = Schema.ensure(self.resolve_schema(other, v))
                    wrapped = wrap_meta_structure(v, resolved)
                    self[other] = wrapped
                    return self


                elif isinstance(self, list):
                    if len(args) == 1:
                        new_items = args[0]
                        for v in (new_items if isinstance(new_items, Iterable) else [new_items]):
                            self.add(None, v)
                    elif len(args) == 2 and isinstance(args[0], int):
                        # Set at index
                        index, val = other, v

                        wrapped = wrap_meta_structure(val, schema=self._infer_sub_schema())
                        self[index] = wrapped
                    else:
                        raise ValueError("Invalid arguments for set()")
                    return self
                elif isinstance(self, set):
                    self.update(other if isinstance(other, Iterable) else [other])

                elif isinstance(self, tuple):
                    data = list(self)
                    data.clear()
                    for val in other:
                        data.append(val)
                    return MetaTuple(data, schema=self._infer_sub_schema())
                    # return MetaTuple(new_values, schema or self.schema)

                else:
                    raise ValueError("Dict or Set or List must use set, not others")
                return self
            raise ValueError("No Arguments Provided in set")

        # TODO Chain get and add missing values if the current one doesn't exist, might need to add a set defaults parameter
        def get(self, key,  default=None, **kwargs):
            if container_type is dict:
                return dict.get(self, key, default)
            elif container_type is list or container_type is tuple:
                if isinstance(key, int):
                    return self[key] if isinstance(key, int) and 0 <= key < len(self) else default
                else:
                    for idx, val in enumerate(self):
                        if val == key:
                            return idx
                    return default
            elif container_type is set:
                return key if key in self else default
            else:
                raise NotImplementedError()

        # def update(self, *args, **kwargs):
        #     other, v = self._pull_args(*args)
        #
        #     if container_type is dict:
        #         if not hasattr(other, "items"):
        #             raise TypeError(f"Expected dict-like input for MetaDict.update(), got {type(other)}")
        #
        #         for k, v in other.items():
        #             resolved = Schema.ensure(self.resolve_schema(k, v))
        #             print(f"[DEBUG] Resolved schema for key={k} → {resolved}")
        #
        #             wrapped = wrap_meta_structure(v, resolved)
        #             if get_origin(self.schema) is dict:
        #                 expected_key_type, value_type = get_args(self.schema)
        #                 if not isinstance(k, expected_key_type):
        #                     raise TypeError(f"[❌] Invalid key type: {type(k)} → expected {expected_key_type}")
        #             dict.__setitem__(self, k, wrapped)
        #
        #     elif container_type is list:
        #         for v in other:
        #             self.add(None, v)
        #     elif container_type is set:
        #         for v in other:
        #             self.add(None, v)
        #     else:
        #         raise NotImplementedError()
        #
        #     return self
        def update(self, *args, **kwargs):
            other, v = self._pull_args(*args)

            if container_type is dict:
                if not hasattr(other, "items"):
                    raise TypeError(f"Expected dict-like input for MetaDict.update(), got {type(other)}")

                # ✅ Coerce keys before validation
                if get_origin(self.schema.schema) is dict:
                    other = coerce_dict_keys(other, self.schema.schema)

                try:
                    for k, v in other.items():
                        resolved = Schema.ensure(self.resolve_schema(k, v))
                        print(f"[DEBUG] Resolved schema for key={k} → {resolved}")

                        wrapped = wrap_meta_structure(v, resolved)
                        if get_origin(self.schema.schema) is dict:
                            expected_key_type, value_type = get_args(self.schema.schema)
                            if not isinstance(k, expected_key_type):
                                raise TypeError(f"[❌] Invalid key type: {type(k)} → expected {expected_key_type}")

                        dict.__setitem__(self, k, wrapped)
                except Exception as e:
                    print("Schema Validation Failed with Schema: ", self.schema.schema)
                    raise Exception(str(e))

            elif container_type is list:
                for v in other:
                    self.add(None, v)
            elif container_type is set:
                for v in other:
                    self.add(None, v)
            else:
                raise NotImplementedError()

            return self

        def pop(self, *args, **kwargs):
            k, v = self._pull_args(*args)
            if container_type is dict:
                return dict.pop(self, k, v)

            elif container_type is list:
                try:
                    return list.pop(self, k)
                except IndexError:
                    return v
            elif container_type is set:
                if not args:
                    return set.pop(self)
                value = args[0]
                if value in self:
                    set.remove(self, value)
                    return value
                return v
            elif container_type is tuple:
                raise TypeError("Tuples are immutable; use .set(new_values) instead")

                # raise KeyError(f"{value} not found in set")
            raise TypeError("Instance is not a dict, list, or set")

        def has(self, key):
            if isinstance(self, list):
                return key in self or (isinstance(key, int) and 0 <= key < len(self))
            return key in self

        def to_native(self):
            if isinstance(self, dict):
                return {k.to_native() if hasattr(k, "to_native") else k: v.to_native() if hasattr(v, "to_native") else v for k, v in self.items()}
            if isinstance(self, set):
                return set(v.to_native() if hasattr(v, "to_native") else v for v in self)
            if isinstance(self, list):
                return [v.to_native() if hasattr(v, "to_native") else v for v in self]
            elif isinstance(self, tuple):
                return tuple(v.to_native() if hasattr(v, "to_native") else v for v in self)
            else:
                # Probably a scalar
                return self.to_native()

        def to_json(self):
            if isinstance(self, dict):
                return {k: v.to_json() if hasattr(v, "to_json") else v for k, v in self.items()}
            elif isinstance(self, (list, set, tuple)):
                return [item.to_json() if hasattr(item, "to_json") else item for item in self]
            else:
                # probably a scalar
                return self.to_json()

        # def validate(self):
        #     if not hasattr(self, "schema") or self.schema is None:
        #         raise ValueError("No schema associated with this node.")
        #     validator = SchemaValidator(self.schema, MetaNodeMixin)
        #     validator.validate_all(self)



        def ensure_iterable(self, v):
            if isinstance(v, (list, set, tuple)):
                return v
            return [v]

        def __setitem__(self, key, value):
            if container_type is dict:
                resolved = Schema.ensure(self.resolve_schema(key, value))
                wrapped = value if isinstance(value, MetaNodeMixin) else wrap_meta_structure(value, resolved)
                # Check key type if needed
                if get_origin(self.schema) is dict:
                    args = get_args(self.schema)
                    if len(args) >= 1:
                        key_type = args[0]
                        if not isinstance(key, key_type):
                            raise TypeError(f"[❌] Invalid key type: {key} (expected {key_type})")

                super().__setitem__(key, wrapped)

            elif container_type in (list, tuple):
                resolved = Schema.ensure(self.resolve_schema(key, value))
                wrapped = value if isinstance(value, MetaNodeMixin) else wrap_meta_structure(value, resolved)
                if isinstance(wrapped, MetaNodeMixin):
                    wrapped.schema = resolved
                    wrapped.validator = SchemaValidator(resolved, MetaNodeMixin)

                super().__setitem__(key, wrapped)

            elif container_type is set:
                raise TypeError("setitem not supported for sets")

            else:
                resolved = Schema.ensure(self.resolve_schema(key, value))
                wrapped = value if isinstance(value, MetaNodeMixin) else wrap_meta_structure(value, resolved)

                super().__setitem__(key, wrapped)

        def __getitem__(self, key):
            return super().__getitem__(key)

        def __repr__(self):
            if isinstance(self, dict):
                return f"{name}({container_type.__repr__(self)})"
            return f"{container_type.__repr__(self)}"

        def __hash__(self):
            return self.to_native()

        def __contains__(self, item):
            if isinstance(self, dict):
                return any(
                    (k.to_native() if isinstance(k, MetaNodeMixin) else k) == item
                    for k in self.keys()
                )
            elif isinstance(self, (list, set)):
                return any(
                    item == (v.to_native() if hasattr(v, "to_native") else v)
                    for v in self
                )
            return False

        def __eq__(self, other):
            return self.to_native() == other

    # Rename the class (important!)
    MetaContainer.__name__ = name
    MetaContainer.__qualname__ = name
    MetaContainer.__module__ = "__main__"  # optional, helps with pickling/debugging
    # MetaContainer.__repr__ = lambda self: f"<{name} {super().__repr__()}>"

    return MetaContainer


# --- Create the Meta* classes ---
MetaDict = create_meta_node_class(dict)
MetaList = create_meta_node_class(list)
MetaSet = create_meta_node_class(set)
MetaStr = create_meta_node_class(str)
MetaInt = create_meta_node_class(int)
MetaFloat = create_meta_node_class(float)
MetaTuple = create_meta_node_class(tuple)


# --- Registry ---
META_TYPE_MAP = {
    bool: MetaBool,          # ✅ Checked before int
    int: MetaInt,
    float: MetaFloat,
    str: MetaStr,
    dict: MetaDict,
    list: MetaList,
    tuple: MetaTuple,
    set: MetaSet,
    type(None): MetaNone
}


meta_class_registry = {
    "MetaDict": MetaDict,
    "MetaList": MetaList,
    "MetaSet": MetaSet,
    "MetaStr": MetaStr,
    "MetaInt": MetaInt,
    "MetaFloat": MetaFloat,
    "MetaBool": MetaBool,
    "MetaNone": MetaNone,
    "MetaTuple": MetaTuple
}

META_TYPES = MetaDict | MetaList | MetaSet | MetaInt | MetaBool | MetaNone | MetaStr | MetaTuple

def coerce_dict_keys(data: dict, schema: Any) -> dict:
    origin = get_origin(schema)
    args = get_args(schema)

    # If schema is Dict[K, V]
    if origin is dict and len(args) == 2:
        key_type, value_type = args

        def coerce_key(k):
            if key_type is int and isinstance(k, str) and k.isdigit():
                return int(k)
            elif key_type is float and isinstance(k, str):
                try:
                    return float(k)
                except ValueError:
                    return k
            return k

        coerced = {}
        for k, v in data.items():
            coerced_k = coerce_key(k)
            # recurse only on nested dicts
            if isinstance(v, dict):
                coerced_v = coerce_dict_keys(v, value_type)
            else:
                coerced_v = v
            coerced[coerced_k] = coerced_v
        return coerced

    return data  # no coercion

def wrap_meta_structure(data: Any, schema: Any = None, **kwargs):
    """
    Wrap data into a MetaNodeMixin subclass according to its schema.
    Each wrapped node will carry its own Schema (with its own validator).
    """

    fill_defaults = kwargs.get("fill_defaults", False)

    if isinstance(data, MetaNodeMixin):
        if schema is not None:
            data.schema = schema if isinstance(schema, Schema) else Schema(schema, **kwargs)
        return data



    schema_obj = schema if isinstance(schema, Schema) else Schema(schema, **kwargs)

    for base_type, meta_cls in META_TYPE_MAP.items():
        if isinstance(data, base_type):

            if base_type is dict:
                raw_data = coerce_dict_keys(data, schema_obj.schema)
                if fill_defaults and isinstance(schema_obj.schema, dict):
                    fill_missing_keys(raw_data, schema_obj.schema)

                wrapped = {}
                for k, v in raw_data.items():
                    coerced_k = schema_obj.coerce_key(k)
                    sub_schema = schema_obj.resolve_from(coerced_k, v)
                    wrapped[coerced_k] = wrap_meta_structure(v, schema=sub_schema, **kwargs)

                node = meta_cls(wrapped, schema=schema_obj, **kwargs)

                validator = schema_obj.build_validator()
                if validator:
                    validator.validate_all(node)
                return node

            elif base_type in (list, set, tuple):
                sub_schema = schema_obj(data)  # still works
                container_data = [
                    wrap_meta_structure(i, schema=sub_schema, **kwargs)
                    for i in data
                ]
                node = meta_cls(container_data if base_type != set else set(container_data), schema=schema_obj, **kwargs)
                # node.schema = schema_obj
                validator = schema_obj.build_validator()
                if validator:
                    validator.validate_all(node)
                return node

            else:  # Scalar types
                node = meta_cls(data, schema=schema_obj, **kwargs)
                validator = schema_obj.build_validator()
                if validator:
                    validator.validate_all(node)
                # return node
                return node

    raise TypeError(f"Unsupported type in wrap_meta_structure: {type(data)}")
