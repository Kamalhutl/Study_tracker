from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from apps.exams.models import (
    BodyType,
    ConductingBody,
    CycleStatus,
    Exam,
    ExamCategory,
    ExamCycle,
    ExamEligibility,
    ExamLevel,
    ExamStage,
    StageMode,
)


class Command(BaseCommand):
    help = "Seed exam reference data (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Print without saving")
        parser.add_argument("--only", type=str, help="Slug of exam to seed (optional)")

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)
        only_slug = options.get("only")
        seed_data = self.get_seed_data()
        if only_slug:
            seed_data = [e for e in seed_data if e["slug"] == only_slug]
        if dry_run:
            self.stdout.write("DRY RUN: would create/update the following exams:")
            for item in seed_data:
                self.stdout.write(f"  - {item['name']} ({item['slug']})")
            return
        created = 0
        updated = 0
        with transaction.atomic():
            for item in seed_data:
                body, _ = ConductingBody.objects.get_or_create(
                    slug=slugify(item["conducting_body"]),
                    defaults={
                        "name": item["conducting_body"],
                        "short_name": item.get("short_name", ""),
                        "body_type": item.get("body_type", BodyType.CENTRAL),
                        "state": item.get("state", ""),
                        "website": item.get("website", ""),
                        "is_active": True,
                    },
                )
                exam, created_flag = Exam.objects.update_or_create(
                    slug=item["slug"],
                    defaults={
                        "name": item["name"],
                        "short_name": item.get("short_name", ""),
                        "conducting_body": body,
                        "category": item["category"],
                        "level": item["level"],
                        "description": item.get("description", ""),
                        "official_url": item.get("official_url", ""),
                        "typical_month": item.get("typical_month"),
                        "is_active": True,
                    },
                )
                if created_flag:
                    created += 1
                else:
                    updated += 1
                # Cycles
                for cyc_data in item.get("cycles", []):
                    cycle, _ = ExamCycle.objects.update_or_create(
                        exam=exam,
                        year=cyc_data["year"],
                        cycle_label=cyc_data.get("cycle_label", str(cyc_data["year"])),
                        defaults={
                            "status": cyc_data.get("status", CycleStatus.ANNOUNCED),
                            "notification_date": cyc_data.get("notification_date"),
                            "application_start": cyc_data.get("application_start"),
                            "application_end": cyc_data.get("application_end"),
                            "fee_last_date": cyc_data.get("fee_last_date"),
                            "correction_window_start": cyc_data.get("correction_window_start"),
                            "correction_window_end": cyc_data.get("correction_window_end"),
                            "result_date": cyc_data.get("result_date"),
                            "vacancy_count": cyc_data.get("vacancy_count"),
                            "official_notification_url": cyc_data.get(
                                "official_notification_url", ""
                            ),
                            "notification_pdf_url": cyc_data.get("notification_pdf_url", ""),
                            "source_url": cyc_data.get("source_url", ""),
                            "extraction_confidence": cyc_data.get("extraction_confidence", 100),
                            "verified_by_human": False,
                            "is_published": False,
                            "notes": cyc_data.get("notes", ""),
                        },
                    )
                    # Stages
                    for stage_data in cyc_data.get("stages", []):
                        ExamStage.objects.update_or_create(
                            cycle=cycle,
                            stage_order=stage_data["stage_order"],
                            defaults={
                                "name": stage_data["name"],
                                "mode": stage_data.get("mode", StageMode.ONLINE_CBT),
                                "date_start": stage_data.get("date_start"),
                                "date_end": stage_data.get("date_end"),
                                "is_date_tentative": stage_data.get("is_date_tentative", False),
                                "admit_card_date": stage_data.get("admit_card_date"),
                                "city_intimation_date": stage_data.get("city_intimation_date"),
                                "result_date": stage_data.get("result_date"),
                                "duration_minutes": stage_data.get("duration_minutes"),
                                "total_marks": stage_data.get("total_marks"),
                                "negative_marking": stage_data.get("negative_marking", ""),
                                "is_qualifying_only": stage_data.get("is_qualifying_only", False),
                            },
                        )
                # Eligibility (simplified: attach to exam, no cycle-specific for now)
                elig_data = item.get("eligibility", {})
                ExamEligibility.objects.update_or_create(
                    exam=exam,
                    defaults={
                        "min_age": elig_data.get("min_age"),
                        "max_age": elig_data.get("max_age"),
                        "age_as_on_date": elig_data.get("age_as_on_date"),
                        "age_relaxation": elig_data.get("age_relaxation", {}),
                        "attempts_general": elig_data.get("attempts_general"),
                        "attempts_obc": elig_data.get("attempts_obc"),
                        "attempts_sc_st": elig_data.get("attempts_sc_st"),
                        "attempts_pwbd": elig_data.get("attempts_pwbd"),
                        "min_qualification": elig_data.get("min_qualification", ""),
                        "allow_final_year_appearing": elig_data.get(
                            "allow_final_year_appearing", False
                        ),
                        "nationality_note": elig_data.get("nationality_note", ""),
                        "physical_standards": elig_data.get("physical_standards"),
                        "verified_by_human": False,
                        "source_url": elig_data.get("source_url", item.get("official_url", "")),
                    },
                )
        self.stdout.write(f"Created {created} exams, updated {updated}.")

    def get_seed_data(self):
        # Twelve exams chosen for search volume and breadth
        exams = [
            {
                "slug": "upsc-civil-services",
                "name": "Civil Services Examination",
                "short_name": "UPSC CSE",
                "conducting_body": "Union Public Service Commission",
                "body_type": BodyType.CENTRAL,
                "category": ExamCategory.CIVIL_SERVICES,
                "level": ExamLevel.NATIONAL,
                "typical_month": 2,
                "official_url": "https://www.upsc.gov.in/",
                "cycles": [
                    {
                        "year": 2026,
                        "cycle_label": "2026",
                        "status": CycleStatus.NOTIFICATION_OUT,
                        "notification_date": "2026-02-15",
                        "application_start": "2026-02-15",
                        "application_end": "2026-03-15",
                        "fee_last_date": "2026-03-16",
                        "vacancy_count": 700,
                        "source_url": "https://www.upsc.gov.in/",
                        "stages": [
                            {
                                "stage_order": 1,
                                "name": "Prelims",
                                "mode": StageMode.ONLINE_CBT,
                                "date_start": "2026-06-15",
                            },
                            {
                                "stage_order": 2,
                                "name": "Mains",
                                "mode": StageMode.DESCRIPTIVE,
                                "date_start": "2026-09-20",
                                "is_date_tentative": True,
                            },
                            {
                                "stage_order": 3,
                                "name": "Interview",
                                "mode": StageMode.INTERVIEW,
                                "date_start": "2027-01-10",
                                "is_date_tentative": True,
                            },
                        ],
                        "extraction_confidence": 100,
                    }
                ],
                "eligibility": {
                    "min_age": 21,
                    "max_age": 32,
                    "age_as_on_date": "2026-08-01",
                    "age_relaxation": {
                        "SC/ST": 5,
                        "OBC": 3,
                        "PwBD_General": 10,
                        "PwBD_OBC": 13,
                        "PwBD_SC/ST": 15,
                        "Ex-servicemen": 3,
                    },
                    "attempts_general": 6,
                    "attempts_obc": 9,
                    "attempts_sc_st": None,
                    "attempts_pwbd": 9,
                    "min_qualification": "Bachelor's degree",
                    "allow_final_year_appearing": True,
                    "source_url": "https://www.upsc.gov.in/",
                },
            },
            {
                "slug": "ssc-cgl",
                "name": "Combined Graduate Level Examination",
                "short_name": "SSC CGL",
                "conducting_body": "Staff Selection Commission",
                "body_type": BodyType.CENTRAL,
                "category": ExamCategory.SSC,
                "level": ExamLevel.NATIONAL,
                "typical_month": 3,
                "official_url": "https://ssc.gov.in/",
                "cycles": [
                    {
                        "year": 2026,
                        "cycle_label": "2026",
                        "status": CycleStatus.ANNOUNCED,
                        "source_url": "https://ssc.gov.in/",
                        "vacancy_count": 10000,
                    }
                ],
                "eligibility": {"source_url": "https://ssc.gov.in/"},
            },
            {
                "slug": "ssc-chsl",
                "name": "Combined Higher Secondary Level Examination",
                "short_name": "SSC CHSL",
                "conducting_body": "Staff Selection Commission",
                "body_type": BodyType.CENTRAL,
                "category": ExamCategory.SSC,
                "level": ExamLevel.NATIONAL,
                "typical_month": 4,
                "official_url": "https://ssc.gov.in/",
                "cycles": [
                    {
                        "year": 2026,
                        "cycle_label": "2026",
                        "status": CycleStatus.ANNOUNCED,
                        "source_url": "https://ssc.gov.in/",
                    }
                ],
                "eligibility": {"source_url": "https://ssc.gov.in/"},
            },
            {
                "slug": "ibps-po",
                "name": "Probationary Officer",
                "short_name": "IBPS PO",
                "conducting_body": "Institute of Banking Personnel Selection",
                "body_type": BodyType.BANKING,
                "category": ExamCategory.BANKING,
                "level": ExamLevel.NATIONAL,
                "typical_month": 8,
                "official_url": "https://www.ibps.in/",
                "cycles": [
                    {
                        "year": 2026,
                        "cycle_label": "2026-27",
                        "status": CycleStatus.ANNOUNCED,
                        "source_url": "https://www.ibps.in/",
                    }
                ],
                "eligibility": {"source_url": "https://www.ibps.in/"},
            },
            {
                "slug": "ibps-clerk",
                "name": "Clerk",
                "short_name": "IBPS Clerk",
                "conducting_body": "Institute of Banking Personnel Selection",
                "body_type": BodyType.BANKING,
                "category": ExamCategory.BANKING,
                "level": ExamLevel.NATIONAL,
                "typical_month": 9,
                "official_url": "https://www.ibps.in/",
                "cycles": [
                    {
                        "year": 2026,
                        "cycle_label": "2026-27",
                        "status": CycleStatus.ANNOUNCED,
                        "source_url": "https://www.ibps.in/",
                    }
                ],
                "eligibility": {"source_url": "https://www.ibps.in/"},
            },
            {
                "slug": "sbi-po",
                "name": "Probationary Officer",
                "short_name": "SBI PO",
                "conducting_body": "State Bank of India",
                "body_type": BodyType.BANKING,
                "category": ExamCategory.BANKING,
                "level": ExamLevel.NATIONAL,
                "typical_month": 4,
                "official_url": "https://sbi.bank.in/web/careers",
                "cycles": [
                    {
                        "year": 2026,
                        "cycle_label": "2026-27",
                        "status": CycleStatus.ANNOUNCED,
                        "source_url": "https://sbi.bank.in/web/careers",
                    }
                ],
                "eligibility": {"source_url": "https://sbi.bank.in/web/careers"},
            },
            {
                "slug": "rrb-ntpc",
                "name": "Non-Technical Popular Categories",
                "short_name": "RRB NTPC",
                "conducting_body": "Railway Recruitment Board",
                "body_type": BodyType.RAILWAY,
                "category": ExamCategory.RAILWAY,
                "level": ExamLevel.NATIONAL,
                "typical_month": 2,
                "official_url": "https://rrbapply.gov.in/",
                "cycles": [
                    {
                        "year": 2026,
                        "cycle_label": "2026",
                        "status": CycleStatus.ANNOUNCED,
                        "source_url": "https://rrbapply.gov.in/",
                    }
                ],
                "eligibility": {"source_url": "https://rrbapply.gov.in/"},
            },
            {
                "slug": "ctet",
                "name": "Central Teacher Eligibility Test",
                "short_name": "CTET",
                "conducting_body": "Central Board of Secondary Education",
                "body_type": BodyType.CENTRAL,
                "category": ExamCategory.TEACHING,
                "level": ExamLevel.NATIONAL,
                "typical_month": 7,
                "official_url": "https://ctet.nic.in/",
                "cycles": [
                    {
                        "year": 2026,
                        "cycle_label": "2026",
                        "status": CycleStatus.ANNOUNCED,
                        "source_url": "https://ctet.nic.in/",
                    }
                ],
                "eligibility": {"source_url": "https://ctet.nic.in/"},
            },
            {
                "slug": "ugc-net",
                "name": "UGC NET",
                "short_name": "UGC NET",
                "conducting_body": "National Testing Agency",
                "body_type": BodyType.TESTING_AGENCY,
                "category": ExamCategory.TEACHING,
                "level": ExamLevel.NATIONAL,
                "typical_month": 6,
                "official_url": "https://ugcnet.nta.ac.in/",
                "cycles": [
                    {
                        "year": 2026,
                        "cycle_label": "June 2026",
                        "status": CycleStatus.ANNOUNCED,
                        "source_url": "https://ugcnet.nta.ac.in/",
                    }
                ],
                "eligibility": {"source_url": "https://ugcnet.nta.ac.in/"},
            },
            {
                "slug": "gate",
                "name": "Graduate Aptitude Test in Engineering",
                "short_name": "GATE",
                "conducting_body": "IISc Bangalore (rotating)",
                "body_type": BodyType.TESTING_AGENCY,
                "category": ExamCategory.ENGINEERING,
                "level": ExamLevel.NATIONAL,
                "typical_month": 2,
                "official_url": "https://gate.iisc.ac.in/",
                "cycles": [
                    {
                        "year": 2027,
                        "cycle_label": "2027",
                        "status": CycleStatus.ANNOUNCED,
                        "source_url": "https://gate.iisc.ac.in/",
                    }
                ],
                "eligibility": {"source_url": "https://gate.iisc.ac.in/"},
            },
            {
                "slug": "neet-ug",
                "name": "NEET UG",
                "short_name": "NEET UG",
                "conducting_body": "National Testing Agency",
                "body_type": BodyType.TESTING_AGENCY,
                "category": ExamCategory.MEDICAL,
                "level": ExamLevel.NATIONAL,
                "typical_month": 5,
                "official_url": "https://neet.nta.nic.in/",
                "cycles": [
                    {
                        "year": 2026,
                        "cycle_label": "2026",
                        "status": CycleStatus.ANNOUNCED,
                        "source_url": "https://neet.nta.nic.in/",
                    }
                ],
                "eligibility": {"source_url": "https://neet.nta.nic.in/"},
            },
            {
                "slug": "jee-main",
                "name": "JEE Main",
                "short_name": "JEE Main",
                "conducting_body": "National Testing Agency",
                "body_type": BodyType.TESTING_AGENCY,
                "category": ExamCategory.ENGINEERING,
                "level": ExamLevel.NATIONAL,
                "typical_month": 4,
                "official_url": "https://jeemain.nta.nic.in/",
                "cycles": [
                    {
                        "year": 2026,
                        "cycle_label": "Session 1",
                        "status": CycleStatus.ANNOUNCED,
                        "source_url": "https://jeemain.nta.nic.in/",
                    }
                ],
                "eligibility": {"source_url": "https://jeemain.nta.nic.in/"},
            },
        ]
        return exams
