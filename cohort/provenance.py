from collections.abc import Iterable
from dataclasses import dataclass
from hashlib import sha256
import json

from cohort.eligibility import EffectiveInspection


@dataclass(frozen=True, slots=True)
class CohortProvenance:
    cohort_id: str
    revision_id: int
    digest: str


def build_provenance(
    cohort_id: str, revision_id: int, members: Iterable[EffectiveInspection]
) -> CohortProvenance:
    ordered = sorted(members, key=lambda member: member.observation.inspection_id)
    payload = {
        'cohort_id': cohort_id,
        'revision_id': revision_id,
        'members': [
            {
                'inspection_id': member.observation.inspection_id,
                'batch_id': member.observation.batch_id,
                'parent_kind': member.observation.parent_kind,
                'cursor': member.observation.cursor,
                'original': member.observation.offspring,
                'effective': member.offspring,
                'amendment_revision_id': member.amendment_revision_id,
            }
            for member in ordered
        ],
    }
    body = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return CohortProvenance(cohort_id, revision_id, sha256(body).hexdigest())


def verify_provenance(provenance: CohortProvenance, members: Iterable[EffectiveInspection]) -> bool:
    return provenance == build_provenance(provenance.cohort_id, provenance.revision_id, members)
