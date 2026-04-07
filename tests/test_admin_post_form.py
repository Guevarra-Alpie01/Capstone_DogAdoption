from django.test import TestCase

from dogadoption_admin.barangays import BAYAWAN_BARANGAYS
from dogadoption_admin.forms import PostForm
from dogadoption_admin.models import Post


class AdminPostFormTests(TestCase):
    def test_location_field_uses_28_barangay_dropdown(self):
        form = PostForm()

        self.assertEqual(form.fields["location"].__class__.__name__, "ChoiceField")
        self.assertEqual(form.fields["location"].choices[0], ("", "Select barangay"))
        self.assertEqual(
            [value for value, _label in form.fields["location"].choices[1:29]],
            list(BAYAWAN_BARANGAYS),
        )

    def test_breed_and_color_choices_include_expanded_options(self):
        breed_choices = dict(Post.BREED_CHOICES)
        color_choices = dict(Post.COLOR_CHOICES)

        self.assertIn("american_bully", breed_choices)
        self.assertIn("japanese_spitz", breed_choices)
        self.assertIn("yorkshire_terrier", breed_choices)
        self.assertIn("blue", color_choices)
        self.assertIn("fawn", color_choices)
        self.assertIn("spotted", color_choices)
