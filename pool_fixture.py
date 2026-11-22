"""Seed and inspect the frozen source cohorts used in POOL.md."""
from contextlib import closing
import json
import sqlite3

from cohort.amendments import amend
from cohort.freeze import freeze
from cohort.revisions import RevisionStore
from demo import initialize_source
from models.frequency import count_frequencies
from trials.batches import BatchStore
from trials.completion import record


def load_pool_sample(source):
    """Load the worksheet into an initialized, empty source database."""
    batch = BatchStore(source).open("pool-day")
    identities = {label: f"pool-inspection-{label}" for label in "xyzwpb"}
    for label in "xyzw":
        record(source, batch.batch_id, identities[label], "A", ())
    record(source, batch.batch_id, identities["p"], "A", ("A", "B"))
    record(source, batch.batch_id, identities["b"], "B", ("A",))
    base = RevisionStore(source).create_base()
    swapped_x = amend(source, base.revision_id, identities["x"], ("A", "B"))
    swapped_both = amend(source, swapped_x.revision_id, identities["p"], ())

    def cohort(revision, labels):
        return freeze(source, revision.revision_id, [identities[label] for label in labels])

    first = cohort(base, "xypb")
    second = cohort(base, "xzb")
    only_b = cohort(base, "b")
    return {
        "common_three": (first, second, cohort(base, "xwb")),
        "separate_pairs": (first, second, cohort(base, "yzb")),
        "swapped": (cohort(base, "xpb"), cohort(swapped_both, "xpb"), only_b),
        "split": (cohort(base, "xp"), only_b),
    }


def main():
    with closing(sqlite3.connect(":memory:")) as source:
        initialize_source(source)
        samples = load_pool_sample(source)
        common = tuple(map(count_frequencies, samples["common_three"]))
        paired = tuple(map(count_frequencies, samples["separate_pairs"]))
        old, changed, _ = samples["swapped"]
        if common != paired or count_frequencies(old) != count_frequencies(changed):
            raise AssertionError("the source marginals must agree")
        if old.members == changed.members or old.provenance == changed.provenance:
            raise AssertionError("the swapped cohort must preserve a distinct frozen revision")
        print(json.dumps({
            "single_cohort_A_sizes": [a.sample_size for a, _ in common],
            "single_cohort_A_AB_probabilities": [str(a.probability(("A", "B"))) for a, _ in common],
            "swapped_A_AB_probability": str(count_frequencies(changed)[0].probability(("A", "B"))),
        }, sort_keys=True))


if __name__ == "__main__":
    main()
