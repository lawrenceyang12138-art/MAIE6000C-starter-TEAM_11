from __future__ import annotations

from services.common.db import get_session_factory
from services.common.models import Case, CaseStatus, Job, JobStatus

DEMO_CASES = [
    {
        "title": "Cannot login to operations portal",
        "description": (
            "User reports password reset did not restore access to the "
            "operations dashboard."
        ),
    },
    {
        "title": "Invoice charge looks incorrect",
        "description": (
            "Customer believes this month includes an unexpected duplicate "
            "billing charge."
        ),
    },
    {
        "title": "Production service outage alert",
        "description": "Several users report the service is down and requests are failing.",
    },
]


def main() -> None:
    session_factory = get_session_factory()

    with session_factory() as db:
        for item in DEMO_CASES:
            case = Case(
                title=item["title"],
                description=item["description"],
                status=CaseStatus.QUEUED.value,
            )
            db.add(case)
            db.flush()

            db.add(
                Job(
                    case_id=case.id,
                    status=JobStatus.PENDING.value,
                )
            )

        db.commit()

    print(f"Seeded {len(DEMO_CASES)} demo cases.")


if __name__ == "__main__":
    main()
