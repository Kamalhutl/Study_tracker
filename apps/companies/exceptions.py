"""Company-domain exceptions, each with a stable machine ``code`` for the API layer."""


class CompanyError(Exception):
    code = "company_error"


class DuplicateCompany(CompanyError):
    code = "duplicate_company"


class BlockedDomain(CompanyError):
    code = "blocked_domain"


class InvalidCompanyTransition(CompanyError):
    code = "invalid_company_transition"


class CandidateAlreadyDecided(CompanyError):
    code = "candidate_already_decided"


class DetectionNotApplicable(CompanyError):
    code = "detection_not_applicable"
