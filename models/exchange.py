from dataclasses import dataclass
from hashlib import sha256
from hmac import compare_digest
import json

from models.codec import decode_law, decode_origin, encode_law, encode_origin, require_fields
from models.law import FrozenLaw


@dataclass(frozen=True, slots=True)
class ModelEdition:
    law: FrozenLaw
    text: str


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _body_digest(body: object) -> str:
    return sha256(_canonical(body).encode('utf-8')).hexdigest()


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON field {key!r}')
        result[key] = value
    return result


def encode_edition(law: FrozenLaw) -> str:
    body = encode_law(law)
    return _canonical({
        'version': 1,
        'origin': encode_origin(law.origin),
        'body': body,
        'body_sha256': _body_digest(body),
    })


def decode_edition(text: str) -> ModelEdition:
    if not isinstance(text, str):
        raise ValueError('edition must be JSON text')
    value = json.loads(text, object_pairs_hook=_unique_object)
    fields = require_fields(value, {'version', 'origin', 'body', 'body_sha256'}, 'edition')
    if type(fields['version']) is not int or fields['version'] != 1:
        raise ValueError('unsupported edition version')
    digest = fields['body_sha256']
    if (
        not isinstance(digest, str) or not digest.isascii()
        or not compare_digest(digest, _body_digest(fields['body']))
    ):
        raise ValueError('edition body digest mismatch')
    law = decode_law(fields['body'])
    if decode_origin(fields['origin']) != law.origin:
        raise ValueError('edition origin does not match the body origin')
    return ModelEdition(law, text)
