import pytest
from django.urls import reverse
from django.contrib.auth import get_user_model
from calculator.models import Project

User = get_user_model()

@pytest.mark.django_db
class TestAuthAccess:

    def setup_method(self):
        # Create two users
        self.alice = User.objects.create_user(username="alice", password="pass1234")
        self.bob = User.objects.create_user(username="bob", password="pass1234")

        # Create projects with different owners
        self.p1 = Project.objects.create(owner=self.alice, name="Alice's Project")
        self.p2 = Project.objects.create(owner=self.bob, name="Bob's Project")

    # Test login required for protected pages
    def test_login_required_redirects(self, client, settings):
        login_url = settings.LOGIN_URL
        resp = client.get(reverse("project_list"))
        assert resp.status_code in (301, 302)
        assert login_url in resp.url

    # Test users can only view their own projects
    def test_owner_can_view_own_project(self, client):
        client.login(username="alice", password="pass1234")
        resp = client.get(reverse("project_detail", args=[self.p1.id]))
        assert resp.status_code == 200
        assert "Alice's Project" in resp.content.decode()

    def test_owner_cannot_view_others_project(self, client):
        client.login(username="alice", password="pass1234")
        resp = client.get(reverse("project_detail", args=[self.p2.id]))
        assert resp.status_code in (403, 404)

    # Test project creation binds to user
    def test_create_binds_owner(self, client):
        client.login(username="alice", password="pass1234")
        url = reverse("project_create")
        resp = client.post(url, {"name": "New Project", "description": "Test project"})
        assert resp.status_code == 200
        new_project = Project.objects.get(name="New Project")
        assert new_project.owner == self.alice

    # Test access to protected calculator page
    def test_calculator_requires_ownership(self, client):
        client.login(username="alice", password="pass1234")
        url = reverse("project_calculator", args=[self.p2.id])
        resp = client.get(url)
        assert resp.status_code in (403, 404)

    # Test user logout redirects to login
    def test_logout_redirects(self, client):
        client.login(username="alice", password="pass1234")
        client.logout()
        resp = client.get(reverse("project_list"))
        assert resp.status_code in (301, 302)
        assert settings.LOGIN_URL in resp.url
