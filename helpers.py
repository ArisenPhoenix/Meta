from typing import Any, Union, get_origin, get_args

def is_type_match(value, expected_type, base_class) -> bool:
    if isinstance(value, base_class):
        value = value.to_native()

    origin = get_origin(expected_type)
    args = get_args(expected_type)

    # Handle Union[...] properly
    if origin is Union:
        return any(is_type_match(value, t, base_class) for t in args)

    # List check
    if origin is list:
        if not isinstance(value, list):
            return False
        (item_type,) = args if args else (Any,)
        return all(is_type_match(v, item_type, base_class) for v in value)

    # Set check
    if origin is set:
        if not isinstance(value, set):
            return False
        (item_type,) = args if args else (Any,)
        return all(is_type_match(v, item_type, base_class) for v in value)

    # Dict check
    if origin is dict:
        if not isinstance(value, dict):
            return False
        key_type, val_type = args if len(args) == 2 else (Any, Any)
        return all(
            is_type_match(k, key_type, base_class) and is_type_match(v, val_type, base_class)
            for k, v in value.items()
        )

    if origin is tuple:
        if not isinstance(value, tuple):
            return False
        if args and args[-1] is Ellipsis:
            item_type = args[0]
            return all(is_type_match(v, item_type, base_class) for v in value)
        if len(args) != len(value):
            return False
        return all(is_type_match(v, t, base_class) for v, t in zip(value, args))

    # Fallback for built-in types
    if isinstance(expected_type, type):
        return isinstance(value, expected_type)

    # Generic fallback for things like typing.Any
    return True

def resolve_schema_key(key, schema):
    origin = get_origin(schema)
    args = get_args(schema)

    if schema is None:
        return None

    # ✅ Dict[T, V]
    if origin is dict and len(args) == 2:
        _, value_type = args
        return value_type

    # ✅ Explicit schema dict, like {"name": str, str: int}
    if isinstance(schema, dict):
        # 1. Try direct key match
        if key in schema:
            return schema[key]

        # 2. Try matching by key type
        for k_type, v_type in schema.items():
            if isinstance(k_type, type) and isinstance(key, k_type):
                return v_type

    return None


def validate_container_origins(origin, value, args, path, validate_type):
    if origin is list and isinstance(value, list):
        subtype = args[0] if args else Any
        for i, item in enumerate(value):
            # self._validate_type(subtype, item, path=f"{path}[{i}]")
            validate_type(subtype, item, path=f"{path}[{i}]")
        return

    if origin is set and isinstance(value, set):
        subtype = args[0] if args else Any
        for item in value:
            # self._validate_type(subtype, item, path=f"{path}{{{item}}}")
            validate_type(subtype, item, path=f"{path}{{{item}}}")
        return

    if origin is dict and isinstance(value, dict):
        key_type, val_type = args if len(args) == 2 else (Any, Any)
        for k, v in value.items():
            validate_type(key_type, k, path=f"{path}.key")
            validate_type(key_type, k, path=f"{path}.k")
            # self._validate_type(key_type, k, path=f"{path}.key")
            # self._validate_type(val_type, v, path=f"{path}.{k}")
        return


def validate_dict(expected, value, path, validate_type):
    # --- Dict ---
    if isinstance(expected, dict) and isinstance(value, dict):
        for k, sub_schema in expected.items():
            if k in value:
                # self._validate_type(sub_schema, value[k], path=f"{path}.{k}")
                validate_type(sub_schema, value[k], path=f"{path}.{k}")
        return

def validate_list(expected, value, path, validate_type):
    if isinstance(expected, list) and isinstance(value, list):
        subtype = expected[0] if expected else Any
        for i, item in enumerate(value):
            # self._validate_type(subtype, item, path=f"{path}[{i}]")
            validate_type(subtype, item, path=f"{path}[{i}]")
        return

def validate_set(expected, value, path, validate_type):
    if isinstance(expected, set) and isinstance(value, set):
        subtype = next(iter(expected)) if expected else Any
        for item in value:
            # self._validate_type(subtype, item, path=f"{path}{{{item}}}")
            validate_type(subtype, item, path=f"{path}{{{item}}}")
        return


def is_key_instance_of_type(key, key_type) -> bool:
    try:
        origin = get_origin(key_type)
        args = get_args(key_type)

        if origin is Union:
            return any(is_key_instance_of_type(key, t) for t in args)

        if isinstance(key_type, set):
            return any(is_key_instance_of_type(key, t) for t in key_type)

        return isinstance(key, key_type)

    except TypeError:
        return False


def get_default_from_type(tp):
    # ✅ Handle tuple of types (e.g., Union)
    if isinstance(tp, tuple):
        return get_default_from_type(tp[0])  # choose first type as fallback

    # ✅ Handle set type
    if isinstance(tp, set):
        return set()

    # ✅ Handle list type
    if isinstance(tp, list):
        return []

    # ✅ Handle tuple type
    if isinstance(tp, tuple) and Ellipsis in tp:
        return tuple()
    if isinstance(tp, tuple):
        return tuple(get_default_from_type(t) for t in tp)

    # ✅ Handle dict type
    if isinstance(tp, dict):
        return {}

    # ✅ Handle concrete types
    if tp in (int, float, str, bool):
        return tp()

    if tp is None or tp is type(None):
        return None

    try:
        return tp()
    except Exception:
        return None

def coerce_key_to_type(key: Any, key_type: Any) -> Any:
    try:
        return key_type(key)
    except Exception:
        return key


def coerce_dict_keys(data: dict, schema: Any) -> dict:
    if not isinstance(data, dict) or not isinstance(schema, dict):
        return data

    coerced = {}
    for k, v in data.items():
        matched_key_type = None
        original_key = k  # Save for fallback

        for sk in schema.keys():
            if sk == k:
                matched_key_type = sk
                break
            if isinstance(sk, type) and isinstance(k, str):
                try:
                    test_k = coerce_key_to_type(k, sk)
                    if isinstance(test_k, sk):
                        matched_key_type = sk
                        k = test_k
                        break
                except Exception:
                    continue
            if isinstance(sk, tuple) and all(isinstance(t, type) for t in sk):
                for t in sk:
                    try:
                        test_k = coerce_key_to_type(k, t)
                        if isinstance(test_k, t):
                            matched_key_type = sk
                            k = test_k
                            break
                    except Exception:
                        continue
                if matched_key_type:
                    break

        subschema = schema.get(matched_key_type, None)

        # --- Coerce value types based on schema ---
        if isinstance(subschema, set):
            expected_type = next(iter(subschema), Any)
            if isinstance(v, list):
                coerced_v = set(expected_type(item) for item in v)
            else:
                coerced_v = v if isinstance(v, set) else set([expected_type(v)])

        elif isinstance(subschema, list):
            expected_type = subschema[0] if subschema else Any
            if isinstance(v, list):
                coerced_v = [expected_type(item) for item in v]
            else:
                coerced_v = [expected_type(v)]

        elif isinstance(v, dict) and isinstance(subschema, dict):
            coerced_v = coerce_dict_keys(v, subschema)

        else:
            coerced_v = v

        coerced[k] = coerced_v  # ✅ Use the final coerced key and value

    return coerced
#

def coerce_keys_recursively(data: Any, schema: Any) -> Any:
    origin = get_origin(schema)
    args = get_args(schema)

    # --- Dict[K, V] from typing ---
    if origin is dict and isinstance(data, dict):
        key_type, val_type = args if len(args) == 2 else (Any, Any)
        coerced = {}
        for k, v in data.items():
            coerced_key = coerce_key_to_type(k, key_type)
            coerced_val = coerce_keys_recursively(v, val_type)
            coerced[coerced_key] = coerced_val
        return coerced

    # --- Set ---
    if origin is set and isinstance(data, set):
        (item_type,) = args if args else (Any,)
        return {coerce_keys_recursively(i, item_type) for i in data}

    # --- List ---
    if origin is list and isinstance(data, list):
        (item_type,) = args if args else (Any,)
        return [coerce_keys_recursively(i, item_type) for i in data]

    # --- Tuple ---
    if origin is tuple and isinstance(data, tuple):
        if args and args[-1] is Ellipsis:
            return tuple(coerce_keys_recursively(i, args[0]) for i in data)
        return tuple(coerce_keys_recursively(i, s) for i, s in zip(data, args))

    # --- Explicit schema dict: TypedDict-style ---
    if isinstance(schema, dict) and isinstance(data, dict):
        coerced = {}
        for k, v in data.items():
            matched_key = k
            matched_val_schema = Any

            for sk, sv in schema.items():
                if isinstance(sk, type) and isinstance(k, sk):
                    matched_val_schema = sv
                    break
                if isinstance(sk, tuple) and any(isinstance(k, t) for t in sk):
                    matched_val_schema = sv
                    break
                if sk == k:
                    matched_val_schema = sv
                    break

            coerced[matched_key] = coerce_keys_recursively(v, matched_val_schema)
        return coerced

    return data

def normalize_data(data: Any, schema: Any) -> Any:
    origin = get_origin(schema)
    args = get_args(schema)

    # --- typing.Dict[K, V] ---
    if origin is dict and isinstance(data, dict):
        key_type, val_type = args if len(args) == 2 else (Any, Any)
        result = {}
        for k, v in data.items():
            coerced_key = coerce_key_to_type(k, key_type)
            result[coerced_key] = normalize_data(v, val_type)
        return result

    # --- typing.Set[T] ---
    if origin is set:
        item_type = args[0] if args else Any
        if isinstance(data, (list, set)):
            return {normalize_data(i, item_type) for i in data}
        raise TypeError(f"[normalize_data] Expected set or list, got {type(data)}")

    # --- typing.List[T] ---
    if origin is list:
        item_type = args[0] if args else Any
        if not isinstance(data, list):
            raise TypeError(f"[normalize_data] Expected list, got {type(data)}")
        return [normalize_data(i, item_type) for i in data]

    # --- typing.Tuple[T1, T2, ...] or Tuple[T, ...] ---
    if origin is tuple:
        if isinstance(data, list):
            data = tuple(data)
        if not isinstance(data, tuple):
            raise TypeError(f"[normalize_data] Expected tuple, got {type(data)}")
        if args and args[-1] is Ellipsis:
            return tuple(normalize_data(i, args[0]) for i in data)
        return tuple(normalize_data(i, s) for i, s in zip(data, args))

    # --- Explicit schema dict (TypedDict-style) ---
    if isinstance(schema, dict) and isinstance(data, dict):
        normalized = {}
        for k, v in data.items():
            coerced_key = k
            matched_schema = Any

            for sk, sv in schema.items():
                # match against exact key or type
                if sk == k:
                    matched_schema = sv
                    break
                if isinstance(sk, type):
                    try:
                        coerced = coerce_key_to_type(k, sk)
                        if isinstance(coerced, sk):
                            coerced_key = coerced
                            matched_schema = sv
                            break
                    except Exception:
                        continue
                if isinstance(sk, tuple) and all(isinstance(t, type) for t in sk):
                    for t in sk:
                        try:
                            coerced = coerce_key_to_type(k, t)
                            if isinstance(coerced, t):
                                coerced_key = coerced
                                matched_schema = sv
                                break
                        except Exception:
                            continue

            normalized[coerced_key] = normalize_data(v, matched_schema)
        return normalized

    # --- Normalized set schema like {str} ---
    if isinstance(schema, set) and len(schema) == 1:
        (item_type,) = tuple(schema)
        if isinstance(data, (list, set)):
            return {normalize_data(i, item_type) for i in data}
        raise TypeError(f"[normalize_data] Expected list or set for set schema, got {type(data)}")

    # --- Normalized list schema like [int] ---
    if isinstance(schema, list) and len(schema) == 1:
        item_type = schema[0]
        if isinstance(data, list):
            return [normalize_data(i, item_type) for i in data]
        raise TypeError(f"[normalize_data] Expected list for list schema, got {type(data)}")

    # --- Normalized tuple schema like (int, str) or (T, ...) ---
    if isinstance(schema, tuple):
        if isinstance(data, list):
            data = tuple(data)
        if len(schema) == 2 and schema[1] is Ellipsis:
            return tuple(normalize_data(i, schema[0]) for i in data)
        return tuple(normalize_data(i, s) for i, s in zip(data, schema))

    # --- Fallback scalar cast ---
    if isinstance(schema, type):
        try:
            return schema(data)
        except Exception:
            return data

    return data



#
# def normalize_typed_dict(data: Any, schema_dict: dict) -> dict:
#     if not isinstance(data, dict):
#         raise TypeError(f"Expected dict for TypedDict-style schema, got {type(data)}")
#
#     result = {}
#     for k, v in data.items():
#         matched_schema = None
#         coerced_key = k  # Default if no match
#
#         for sk, sv in schema_dict.items():
#             if sk == k:
#                 matched_schema = sv
#                 break
#             elif isinstance(sk, type):
#                 try:
#                     coerced = sk(k) if isinstance(k, str) else k
#                     if isinstance(coerced, sk):
#                         coerced_key = coerced
#                         matched_schema = sv
#                         break
#                 except Exception:
#                     continue
#             elif isinstance(sk, tuple):
#                 for t in sk:
#                     try:
#                         coerced = t(k) if isinstance(k, str) else k
#                         if isinstance(coerced, t):
#                             coerced_key = coerced
#                             matched_schema = sv
#                             break
#                     except Exception:
#                         continue
#                 if matched_schema:
#                     break
#
#         # ✅ Ensure value is normalized recursively
#         result[coerced_key] = normalize_data(v, matched_schema or Any)
#
#     return result
#
#
#
# def normalize_set(data: Any, item_type: Any = Any) -> set:
#     if isinstance(data, (list, set)):
#         return {normalize_data(i, item_type) for i in data}
#     raise TypeError(f"Expected set or list, got {type(data)}")
#
#
# def normalize_list(data: Any, item_type: Any = Any) -> list:
#     if not isinstance(data, list):
#         raise TypeError(f"Expected list, got {type(data)}")
#     return [normalize_data(i, item_type) for i in data]
#
#
# def normalize_tuple(data: Any, args: tuple) -> tuple:
#     if isinstance(data, list):
#         data = tuple(data)
#     if not isinstance(data, tuple):
#         raise TypeError(f"Expected tuple, got {type(data)}")
#     if args and args[-1] is Ellipsis:
#         return tuple(normalize_data(i, args[0]) for i in data)
#     return tuple(normalize_data(i, s) for i, s in zip(data, args))
#
#
# def coerce_scalar(data: Any, typ: type) -> Any:
#     try:
#         return typ(data)
#     except Exception:
#         return data

#
# def normalize_data(data: Any, schema: Any) -> Any:
#     origin = get_origin(schema)
#     args = get_args(schema)
#
#     if isinstance(schema, dict):
#         return normalize_typed_dict(data, schema)
#
#     if origin is dict:
#         key_type, val_type = args if len(args) == 2 else (Any, Any)
#         return normalize_dict(data, key_type, val_type)
#
#     if origin is set:
#         (item_type,) = args if args else (Any,)
#         return normalize_set(data, item_type)
#
#     if origin is list:
#         (item_type,) = args if args else (Any,)
#         return normalize_list(data, item_type)
#
#     if origin is tuple:
#         return normalize_tuple(data, args)
#
#     if isinstance(schema, type):
#         return coerce_scalar(data, schema)
#
#     return data




