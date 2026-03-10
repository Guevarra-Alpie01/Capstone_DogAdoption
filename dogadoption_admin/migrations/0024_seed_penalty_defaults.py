from decimal import Decimal

from django.db import migrations


PENALTY_ROWS = [
    (28, 1, "Rabies vaccination services fee", "50.00", True),
    (28, 2, "Lodging fee", "200.00", True),
    (28, 3, "Impoundment fee", "500.00", True),
    (28, 4, "Lost dog vaccination certificate", "100.00", True),
    (28, 5, "Forced neutering (Male)", "4000.00", True),
    (28, 6, "Forced neutering (Female)", "5000.00", True),
    (28, 7, "Veterinary clearance", "100.00", True),
    (29, 1, "Dog slaughter", "5000.00", True),
    (29, 2, "No proof of vaccination", "2000.00", True),
    (29, 3, "Refusal to register/vaccinate", "2000.00", True),
    (29, 4, "Unvaccinated dog that bite a victim", "5000.00", True),
    (29, 5, "Pay all cost for dog bite victim/s' treatment", "5000.00", True),
    (29, 6, "Refusal to put the biting dog under observation", "5000.00", True),
    (29, 7, "Did not shoulder all expenses of bite victim", "5000.00", True),
    (29, 8, "Failed to shoulder expenses for CLO case filing", "5000.00", True),
    (29, 9, "No dog leash outside", "500.00", True),
    (29, 10, "Collared/tagged dog not under effective control", "1000.00", True),
    (29, 11, "Captured dog without tag", "3000.00", True),
    (29, 12, "Lost vaccination card", "500.00", True),
    (29, 13, "Expired/lapsed anti-rabies vaccination", "100.00", True),
    (29, 14, "4th recorded offense - Forced neutering fine", "5000.00", True),
    (29, 15, "Dog release requirements", "0.00", True),
    (29, 16, "Cruelty to dog", "5000.00", True),
    (29, 17, "Dog slaughtering and dog meat trade court proceedings", "5000.00", True),
    (29, 18, "Electrocution as method of euthanasia", "5000.00", True),
    (29, 19, "Owner liability for grave damage/property and vehicular accident victim hospitalization", "5000.00", True),
    (29, 20, "Redemption fee (within 24 hrs)", "500.00", True),
    (29, 21, "Business establishment harboring stray dog", "5000.00", True),
    (29, 22, "Failure to clean poop in public place", "500.00", True),
    (29, 23, "Forced labor", "5000.00", True),
    (29, 24, "Exceeding 4 heads (1 excess)", "500.00", True),
    (29, 25, "Failure to show proof of vaccination upon house-to-house inspection", "500.00", True),
    (29, 26, "Vet clinic operating without animal facility registration", "5000.00", True),
    (29, 27, "Unregistered dog upon household inspection", "500.00", True),
    (29, 28, "Agri-vet store and pet shop's failure to post rabies info materials", "2500.00", True),
]


def seed_penalty_defaults(apps, schema_editor):
    Penalty = apps.get_model("dogadoption_admin", "Penalty")
    PenaltySection = apps.get_model("dogadoption_admin", "PenaltySection")

    section_by_number = {}
    for section_number in sorted({row[0] for row in PENALTY_ROWS}):
        section = PenaltySection.objects.filter(number=section_number).first()
        if section is None:
            section = PenaltySection.objects.create(number=section_number)
        section_by_number[section_number] = section

    for section_number, penalty_number, title, amount, active in PENALTY_ROWS:
        section = section_by_number[section_number]
        penalty = Penalty.objects.filter(section=section, number=penalty_number).first()
        if penalty is None:
            Penalty.objects.create(
                section=section,
                number=penalty_number,
                title=title,
                amount=Decimal(amount),
                active=active,
            )
            continue

        penalty.title = title
        penalty.amount = Decimal(amount)
        penalty.active = active
        penalty.save(update_fields=["title", "amount", "active"])


class Migration(migrations.Migration):
    dependencies = [
        ("dogadoption_admin", "0023_citation_owner_barangay_citation_owner_first_name_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_penalty_defaults, migrations.RunPython.noop),
    ]

