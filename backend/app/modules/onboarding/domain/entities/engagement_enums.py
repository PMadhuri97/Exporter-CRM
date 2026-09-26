"""Enums for contacts and the activity log — **owner: Developer 3**
(architecture §8.1, §9.3).

Split out of `exporter_enums.py` (L2-01), which now holds only the company's
own values (Developer 2). Unchanged: the database enum it maps to is still
`onboarding.exporter_activity_type_enum`, named on the column in
`exporter_activity.py`, so moving the Python class changes no schema.
"""

import enum


class ExporterActivityType(str, enum.Enum):
    CALL = "CALL"
    MEETING = "MEETING"
    EMAIL = "EMAIL"
    NOTE = "NOTE"
    TASK = "TASK"
    FOLLOW_UP = "FOLLOW_UP"
