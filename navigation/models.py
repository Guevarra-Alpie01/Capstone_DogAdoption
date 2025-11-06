from django.db import models
from django.conf import settings

# Create your models here.

class User(models.Model):
    username = models.CharField(max_length=100)

    class META:
        db_table = "user"