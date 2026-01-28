from django.db import models
from django.contrib.auth.models import User

class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)

    middle_initial = models.CharField(max_length=1, blank=True)
    address = models.TextField()
    age = models.PositiveIntegerField()

    def __str__(self):
        return self.user.username
