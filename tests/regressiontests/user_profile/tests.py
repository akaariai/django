from __future__ import absolute_import, unicode_literals
from django.test import TestCase
from django.test.utils import override_settings
from django.contrib.auth.models import User
from .models import UserProfile


class ProfileTestCase(TestCase):
    def tearDown(self):
        try:
            user = User.objects.get(username="janet")
        except User.DoesNotExist:
            pass
        else:
            user.delete()


    @override_settings(AUTH_PROFILE_MODULE="user_profile.UserProfile")
    def test_get_profile_cache(self):
        janet = User.objects.create_user('janet', 'janet@example.com')

        profile = UserProfile(user=janet, dance='Tango')
        profile.save()

        self.assertEqual(janet.get_profile().dance, 'Tango')

        profile.dance='Salsa'
        profile.save()

        # Testing with kwarg
        self.assertEqual(janet.get_profile().dance, 'Tango')
        self.assertEqual(janet.get_profile(cached=False).dance, 'Salsa')

        profile.dance='Polka'
        profile.save()

        # Testing with arg
        self.assertEqual(janet.get_profile().dance, 'Salsa')
        self.assertEqual(janet.get_profile(False).dance, 'Polka')
        self.assertEqual(janet.get_profile().dance, 'Polka')
