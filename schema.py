from typing import Any, get_origin, get_args, Union, Dict, List, Set, Tuple
import types
from schema_validator import SchemaValidator, NoOpValidator
from Meta.helpers import get_default_from_type

def fill_missing_keys(data: dict, schema: dict):
    for key, expected_type in schema.items():
        if isinstance(key, type):
            continue  # skip fallback rules like str: set()

        if key not in data or data[key] is None:
            data[key] = get_default_from_type(expected_type)
        elif isinstance(data[key], dict) and isinstance(expected_type, dict):
            fill_missing_keys(data[key], expected_type)

class Schema:
    def __init__(self, raw_schema: Any, *, validator_cls=SchemaValidator, **kwargs):
        self.schema = self._normalize_schema(raw_schema) if raw_schema else None
        self.validator_cls = validator_cls if self.schema and validator_cls else NoOpValidator
        self._validator_instance = None if self.validator_cls else lambda x: None
        self.kwargs = kwargs
        self._validate = kwargs.get("validate", isinstance(self.schema, (dict, list, tuple, set, bool, str, int)))

    @staticmethod
    def ensure(value: Any, **kwargs) -> "Schema":
        return value if isinstance(value, Schema) else Schema(value, **kwargs)

    def _normalize_schema(self, schema):
        origin = get_origin(schema)
        args = get_args(schema)

        if isinstance(schema, types.UnionType):  # for Python 3.10+ support of X | Y syntax
            return {self._normalize_schema(arg) for arg in args if arg is not type(None)}

        if origin is Union:
            return {self._normalize_schema(arg) for arg in args if arg is not type(None)}

        if origin in (dict, Dict):
            key_type, val_type = args if len(args) == 2 else (Any, Any)
            norm_key = self._normalize_schema(key_type)
            norm_val = self._normalize_schema(val_type)
            key_tuple = tuple(tuple(sorted(norm_key, key=lambda t: t.__name__))) if isinstance(norm_key,
                                                                                               set) else norm_key
            return {key_tuple: norm_val} if isinstance(key_tuple, tuple) else {key_tuple: norm_val}

        if origin in (list, List):
            item_type = args[0] if args else Any
            return [self._normalize_schema(item_type)]

        if origin in (set, Set):
            item_type = args[0] if args else Any
            return {self._normalize_schema(item_type)}

        if origin in (tuple, Tuple):
            if args and args[-1] is Ellipsis:
                return self._normalize_schema(args[0]), ...
            return tuple(self._normalize_schema(arg) for arg in args)

        if isinstance(schema, dict):
            out = {}
            for k, v in schema.items():
                norm_key = self._normalize_schema(k)
                if isinstance(norm_key, set):
                    norm_key = tuple(sorted(norm_key, key=lambda x: str(x)))
                out[norm_key if isinstance(norm_key, tuple) and len(norm_key) > 1 else norm_key if not isinstance(
                    norm_key, tuple) else norm_key[0]] = self._normalize_schema(v)
            return out

        return schema

    def get(self, key: Any) -> Any:
        if isinstance(self.schema, dict):
            # Exact key match
            if key in self.schema:
                return self.schema[key]
            # Type-based fallback
            for k in self.schema:
                if isinstance(k, type) and isinstance(key, k):
                    return self.schema[k]
                if isinstance(k, tuple) and all(isinstance(t, type) for t in k):
                    if any(isinstance(key, t) for t in k):
                        return self.schema[k]
        if isinstance(self.schema, (list, set, tuple)):
            # Index-style access or default fallback
            if isinstance(key, int) and isinstance(self.schema, list) and key < len(self.schema):
                return self.schema[key]

        if isinstance(key, (str, int, float)):
            for k in self.schema:
                if isinstance(k, tuple) and all(isinstance(t, type) for t in k):
                    if any(isinstance(key, t) for t in k):
                        return self.schema[k]

        raise KeyError(f"Key '{key}' not found in schema")


    def resolve_from(self, key: Any, value: Any = None, level: int = 0, validate: bool = False) -> "Schema":
        """
        Returns a sub-Schema instance for the relevant key or index.
        Always returns a Schema instance, falling back to Schema(Any) if unknown.
        """

        sub_schema_raw = None
        schema = self.schema

        if isinstance(schema, dict):
            if key in schema:
                sub_schema_raw = schema[key]
            else:
                for k_type, v_type in schema.items():
                    if isinstance(k_type, tuple):
                        if any(isinstance(key, t) for t in k_type):
                            sub_schema_raw = v_type
                            break
                    elif isinstance(k_type, type) and isinstance(key, k_type):
                        sub_schema_raw = v_type
                        break

        elif isinstance(schema, (list, set)) and isinstance(key, int):
            try:
                sub_schema_raw = list(schema)[key]
            except IndexError:
                pass

        elif isinstance(schema, tuple):
            if schema[-1] is ...:
                sub_schema_raw = schema[0]
            elif 0 <= level < len(schema):
                sub_schema_raw = schema[level]

        # ✅ Fallback to `Any` if no match was found
        if sub_schema_raw is None:
            sub_schema_raw = Any

        if isinstance(sub_schema_raw, Schema):
            return sub_schema_raw
        return Schema(sub_schema_raw, validate=self._validate, validator_cls=self.validator_cls)

    def coerce_key(self, key: Any) -> Any:
        origin = get_origin(self.schema)
        args = get_args(self.schema)
        if origin is dict and len(args) == 2:
            key_type = args[0]
            try:
                return key_type(key)
            except (ValueError, TypeError):
                return key
        return key

    def __getitem__(self, key: Any) -> Any:
        return self.get(key)

    def __repr__(self):
        return f"<Schema {self.schema}>"

    def __str__(self):
        return str(self.schema)

    def __iter__(self):
        return iter(self.schema)

    def validate(self, data: Any):
        validator = self.build_validator()
        if validator:
            validator.validate_all(data)

    def __call__(self, data: Any, key: Any = None, level: int = 0, validate: bool = True) -> Any:
        """
        Acts as both a validator and resolver: Schema(data) validates,
        or Schema(data, key) gives relevant schema.
        """
        resolved = self.resolve_from(key, data, level, validate=validate)
        return resolved

    def build_validator(self):
        if not self._validate:
            return NoOpValidator()
        if self._validator_instance is None:
            self._validator_instance = self.validator_cls(self.schema)
        return self._validator_instance
