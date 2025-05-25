# --- Schema + Normalization Stubs ---
from abc import abstractmethod
from typing import Union
from Meta.schema_validator import SchemaValidator

class MetaNodeMixin:
    def __new__(cls, *args, **kwargs):
        schema = kwargs.pop("schema", None)
        instance = super().__new__(cls, *args, **kwargs)

        instance.schema = schema
        instance.validator = SchemaValidator(schema, MetaNodeMixin)

        # Validate scalar value directly
        if args and isinstance(instance, (str, int, float, bool)):
            try:
                instance.validator.type_check(args[0], schema, key_path=cls.__name__)
            except Exception as e:
                raise TypeError(f"[ValidationError in {cls.__name__}] {e}")

        elif args and isinstance(args[0], (dict, list, set)):
            try:
                instance.validator.validate_all(args[0])

            except Exception as e:
                raise TypeError(f"[ValidationError in {cls.__name__}] {e}")

        return instance

    def __init__(self, *args, **kwargs):
        schema = getattr(self, "schema", kwargs.get("schema", None))
        self.schema = schema
        self.validator = SchemaValidator(schema, MetaNodeMixin)
        try:
            super().__init__(*args, **kwargs)

        except TypeError:
            pass  # Scalars will raise on init

        # validate the constructed object
        if hasattr(self, "schema") and self.schema is not None:
            try:
                self.validator.validate_all(self)
            except Exception as e:
                raise TypeError(f"[ValidationError in {self.__class__.__name__}] {e}")

    def debug_schema(self):
        print(f"[🧠 Schema Debug] {self.__class__.__name__} schema = {self.schema}")

    def validate(self):
        if not hasattr(self, "schema") or self.schema is None:
            raise ValueError("No schema associated with this node.")
        SchemaValidator(self.schema, MetaNodeMixin).validate_all( self)

    def validate_recursively(self, recursive=False):
        if not hasattr(self, "schema") or self.schema is None:
            raise ValueError("No schema associated with this node.")
        validator = SchemaValidator(self.schema, MetaNodeMixin)
        if recursive and isinstance(self, (dict, list, set)):
            validator.validate_all(self)
        else:
            validator.validate_flat("value", self)

    @property
    def value(self):
        return self.to_native()

    def is_bool(self):
        return isinstance(self.to_native(), bool)

    def is_valid(self):
        try:
            self.validator.validate_all(self)
            return True
        except (TypeError, ValueError, BaseException):
            return False

    def update(self, _):
        pass

    @abstractmethod
    def to_native(self):
        pass


    def __eq__(self, other):
        return self.to_native() == other

    @abstractmethod
    def __setitem__(self, key, value):
        pass

    @abstractmethod
    def __getitem__(self, item):
        pass



# types that cannot be subclassed directly
# --- MetaBool: Subclass of int with bool behavior ---
class MetaBool(int, MetaNodeMixin):
    def __new__(cls, value: Union[bool, int], schema=None):
        coerced = 1 if value else 0

        # --- Perform schema validation BEFORE instantiating ---
        if schema is not None:
            SchemaValidator(schema, MetaBool).type_check(value, schema, key_path="MetaBool")

        instance = super().__new__(cls, coerced)
        instance.schema = schema
        instance.validator = SchemaValidator(schema, MetaBool)
        return instance

    def __init__(self, value: Union[bool, int], schema=None):
        pass

    def get(self, *_): return bool(self)
    def has(self, val): return bool(self) == val
    def set(self, _, val): pass
    def remove(self, _): pass
    def to_native(self): return bool(self)
    def to_json(self): return bool(self)

    def __bool__(self): return int(self) == 1
    def __str__(self): return str(bool(self))
    def __repr__(self): return repr(bool(self))
    def __eq__(self, other): return bool(self) == bool(other)
    def __hash__(self): return self.to_native()
    def __setitem__(self, key, value): pass

    def __getitem__(self, item): return bool(self)


MetaBool.__name__ = "MetaBool"
MetaBool.__qualname__ = "MetaBool"
MetaBool.__module__ = "__main__"

# --- MetaBool: Wrapper for None bool behavior ---
class MetaNone(MetaNodeMixin):
    def __new__(cls, *args, **kwargs):
        return super().__new__(cls)

    def __init__(self, *args, schema=None, **kwargs):
        MetaNodeMixin.__init__(self, schema=schema)

    def get(self, *_): return None
    def has(self, _): return False
    def set(self, *_): pass
    def remove(self, _): pass
    def update(self, _): pass
    def to_native(self): return None
    def to_json(self): return None

    def __repr__(self): return "None"
    def __str__(self): return "None"
    def __eq__(self, other): return other is None or isinstance(other, MetaNone)
    def __hash__(self): return None
    def __bool__(self): return False
    def __setitem__(self, key, value): pass
    def __getitem__(self, item): return None

MetaNone.__name__ = "MetaNone"
MetaNone.__qualname__ = "MetaNone"
MetaNone.__module__ = "__main__"

