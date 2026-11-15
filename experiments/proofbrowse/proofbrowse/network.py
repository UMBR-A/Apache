"""Conservative browser request gate, shared by the CLI and evaluation runner.

This controls HTTP(S) requests visible to Playwright's routing layer; it is NOT
an OS-level or DNS-level network sandbox. See README before visiting untrusted sites.
"""
from __future__ import annotations

from dataclasses import dataclass

from .core import Policy, Refused


@dataclass
class RouteGate:
    """Restrict *all* routed network requests, not only document navigation.

    Third-party resources must be explicitly added to ``resource_domains``;
    adding a resource domain never authorizes document navigation there.
    """

    navigation_policy: Policy
    resource_domains: tuple[str, ...] = ()
    blocked: int = 0
    allowed: int = 0

    def __post_init__(self) -> None:
        # Validate resource scopes even when no page has been loaded yet.
        self.resource_policy = Policy(
            self.navigation_policy.allowed_domains + self.resource_domains,
            self.navigation_policy.max_steps,
        )

    async def __call__(self, route) -> None:
        request = route.request
        policy = self.navigation_policy if request.is_navigation_request() else self.resource_policy
        try:
            policy.check_url(request.url)
        except (Refused, ValueError):
            self.blocked += 1
            await route.abort("blockedbyclient")
            return
        self.allowed += 1
        # Use fallback so test-only fixture routes can fulfill allowed requests.
        await route.fallback()


async def guarded_context(browser, policy: Policy, resource_domains: tuple[str, ...] = ()):
    """Return (browser context, gate). Block SWs to preserve route visibility.

    Route-based filtering does not cover every possible browser-side channel,
    such as DNS rebinding or WebSockets. Use a network sandbox for true isolation.
    """
    context = await browser.new_context(accept_downloads=False, service_workers="block")
    gate = RouteGate(policy, resource_domains)
    await context.route("**/*", gate)
    return context, gate
