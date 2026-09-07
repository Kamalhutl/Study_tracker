from datetime import timedelta
from typing import Any

from apps.jobs.enums import JobStatus, JobType, WorkMode
from apps.jobs.models import Job


def build_job_posting(job: Job) -> dict[str, Any] | None:
    if not job.is_published or job.status != JobStatus.OPEN:
        return None

    data: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
    }

    # title
    data["title"] = job.title

    # description
    if job.description_html_sanitized:
        data["description"] = job.description_html_sanitized
    elif job.description:
        data["description"] = f"<p>{job.description}</p>"

    # datePosted
    data["datePosted"] = (job.posted_at or job.first_seen_at).isoformat()

    # validThrough
    if job.deadline_at:
        data["validThrough"] = job.deadline_at.isoformat()
    else:
        deadline = job.first_seen_at + timedelta(days=60)
        data["validThrough"] = deadline.isoformat()

    # hiringOrganization
    org: dict[str, Any] = {
        "@type": "Organization",
        "name": job.company.name,
    }
    if job.company.domain:
        org["sameAs"] = f"https://{job.company.domain}"
    if job.company.logo_url:
        org["logo"] = job.company.logo_url
    data["hiringOrganization"] = org

    # jobLocation
    location: dict[str, Any] = {
        "@type": "Place",
        "address": {
            "@type": "PostalAddress",
        },
    }
    address = location["address"]
    if job.city:
        address["addressLocality"] = job.city
    if job.state:
        address["addressRegion"] = job.state
    if job.country:
        # Map free text to ISO 3166-1 alpha-2
        country_map = {
            "india": "IN",
            "united states": "US",
            "usa": "US",
            "uk": "GB",
            "united kingdom": "GB",
            "canada": "CA",
            "australia": "AU",
            "germany": "DE",
            "france": "FR",
            "japan": "JP",
            "china": "CN",
            "singapore": "SG",
            "uae": "AE",
            "united arab emirates": "AE",
        }
        country_code = country_map.get(job.country.lower(), "IN")
        address["addressCountry"] = country_code
    else:
        address["addressCountry"] = "IN"
    data["jobLocation"] = location

    # identifier
    if job.source_job_id:
        data["identifier"] = {
            "@type": "PropertyValue",
            "name": job.company.name,
            "value": job.source_job_id,
        }

    # directApply
    data["directApply"] = False

    # baseSalary
    if job.salary_min is not None or job.salary_max is not None:
        salary: dict[str, Any] = {
            "@type": "MonetaryAmount",
            "currency": job.salary_currency or "INR",
        }
        if job.salary_min is not None and job.salary_max is not None:
            salary["value"] = {
                "@type": "QuantitativeValue",
                "minValue": float(job.salary_min),
                "maxValue": float(job.salary_max),
            }
        elif job.salary_min is not None:
            salary["value"] = {
                "@type": "QuantitativeValue",
                "minValue": float(job.salary_min),
            }
        elif job.salary_max is not None:
            salary["value"] = {
                "@type": "QuantitativeValue",
                "maxValue": float(job.salary_max),
            }
        period_map = {
            "hour": "HOUR",
            "hourly": "HOUR",
            "day": "DAY",
            "daily": "DAY",
            "week": "WEEK",
            "weekly": "WEEK",
            "month": "MONTH",
            "monthly": "MONTH",
            "year": "YEAR",
            "yearly": "YEAR",
            "annual": "YEAR",
        }
        unit = period_map.get(job.salary_period.lower(), "MONTH") if job.salary_period else "MONTH"
        salary["unitText"] = unit
        data["baseSalary"] = salary

    # employmentType
    type_map: dict[str, str | None] = {
        JobType.FULL_TIME.value: "FULL_TIME",
        JobType.PART_TIME.value: "PART_TIME",
        JobType.INTERNSHIP.value: "INTERN",
        JobType.CONTRACT.value: "CONTRACTOR",
        JobType.TEMPORARY.value: "TEMPORARY",
        JobType.FREELANCE.value: "CONTRACTOR",
        JobType.UNKNOWN.value: None,
    }
    emp_type = type_map.get(job.job_type)
    if emp_type:
        data["employmentType"] = emp_type

    # work_mode
    if job.work_mode == WorkMode.REMOTE:
        data["jobLocationType"] = "TELECOMMUTE"
        data["applicantLocationRequirements"] = {
            "@type": "Country",
            "name": "Any",
        }
    elif job.work_mode == WorkMode.HYBRID:
        # keep jobLocation, do not set TELECOMMUTE
        pass

    return data
