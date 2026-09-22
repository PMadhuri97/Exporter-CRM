"""Constants shared across the compliance module."""

#: The framework every resolution falls back to. FATF publishes the baseline
#: international standard, so a corridor or a national regulator that has not
#: rated a sector inherits the international view rather than being treated as
#: unrated. This is the only jurisdiction value the lookup knows by name; every
#: other one — including which regulators exist — is data.
FATF_FRAMEWORK = "FATF"
