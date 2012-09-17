from django.db import models
from django.contrib.auth.models import User

class UserProfile(models.Model):
    user = models.OneToOneField(User, related_name="user_profile")
    dance = models.CharField(max_length=100)
