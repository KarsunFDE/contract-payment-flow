package com.karsunfde.contractflow.gateway;

import java.util.List;

import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.core.Ordered;
import org.springframework.http.HttpHeaders;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

/**
 * Propagates the authenticated caller's identity to downstream services as
 * gateway-asserted headers (ADR-0005 §11 — tenant identity is never trusted
 * from the application layer / request body):
 *
 *   X-Tenant-Id ← JWT {@code agency_id} claim
 *   X-User-Id   ← JWT {@code sub} claim
 *   X-User-Role ← JWT {@code role} claim (falls back to the first {@code roles}
 *                 list entry if {@code role} is absent)
 *   X-User-Name ← JWT {@code preferred_username} claim (falls back to {@code name})
 *   X-Agency-Id ← JWT {@code agency_id} claim (same source as X-Tenant-Id —
 *                 ai-orchestrator ingestion reads X-Agency-Id for tenant scope)
 *
 * The COMPLETE identity-header set lives in {@link #IDENTITY_HEADERS}. EVERY one
 * of those headers is stripped from EVERY inbound request unconditionally
 * (header-spoofing defense) — they are set ONLY from verified JWT claims.
 * Downstream services (ai-orchestrator /retrieve and /corpus/*) treat them as
 * the sole source of identity and authorization role, which is safe because
 * those services are only reachable on the compose-internal network through
 * this gateway. Stripping the full set closes a privilege-escalation /
 * cross-tenant hole: a client must not be able to self-assert
 * {@code X-User-Role: sys_admin} or {@code X-Agency-Id: <victim>} and have the
 * orchestrator's require_corpus_admin trust it.
 *
 * Note: the /api/public/** signature-skip path (deliberate debt Item 1,
 * docs/brownfield-debt.md) does not route to ai-orchestrator; on that path
 * no JwtAuthenticationToken is established, so no identity headers are
 * injected — the strip still applies.
 */
@Component
public class ClaimsHeaderFilter implements GlobalFilter, Ordered {

    public static final String TENANT_HEADER = "X-Tenant-Id";
    public static final String USER_HEADER = "X-User-Id";
    public static final String ROLE_HEADER = "X-User-Role";
    public static final String NAME_HEADER = "X-User-Name";
    public static final String AGENCY_HEADER = "X-Agency-Id";

    /**
     * The full set of gateway-asserted identity headers. Defined once so that
     * the inbound strip and the downstream assertion can never drift apart —
     * any header a downstream service trusts for identity/authorization MUST be
     * in this list so it is stripped from client input.
     */
    public static final List<String> IDENTITY_HEADERS = List.of(
        TENANT_HEADER, USER_HEADER, ROLE_HEADER, NAME_HEADER, AGENCY_HEADER);

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        // Always strip inbound identity headers — clients must not be able to
        // assert their own tenant, user, role, name, or agency.
        ServerWebExchange stripped = exchange.mutate()
            .request(r -> r.headers(h -> IDENTITY_HEADERS.forEach(h::remove)))
            .build();

        return stripped.getPrincipal()
            .filter(JwtAuthenticationToken.class::isInstance)
            .cast(JwtAuthenticationToken.class)
            .map(jwtAuth -> {
                Jwt jwt = jwtAuth.getToken();
                String tenantId = jwt.getClaimAsString("agency_id");
                String userId = jwt.getSubject();
                String role = resolveRole(jwt);
                String userName = resolveUserName(jwt);
                // X-Agency-Id shares the agency_id claim with X-Tenant-Id; the
                // orchestrator's ingestion auth reads X-Agency-Id for tenant scope.
                String agencyId = tenantId;
                ServerHttpRequest mutated = stripped.getRequest().mutate()
                    .headers(h -> {
                        setIfPresent(h, TENANT_HEADER, tenantId);
                        setIfPresent(h, USER_HEADER, userId);
                        setIfPresent(h, ROLE_HEADER, role);
                        setIfPresent(h, NAME_HEADER, userName);
                        setIfPresent(h, AGENCY_HEADER, agencyId);
                    })
                    .build();
                return stripped.mutate().request(mutated).build();
            })
            .defaultIfEmpty(stripped)
            .flatMap(chain::filter);
    }

    /** Set a header only when the claim resolved to a non-blank value. */
    private static void setIfPresent(HttpHeaders headers, String name, String value) {
        if (value != null && !value.isBlank()) {
            headers.set(name, value);
        }
    }

    /**
     * Resolve the caller's role. The documented contract (frontend
     * RoleService, ADR-0005) issues a singular {@code role} claim, which the
     * orchestrator's require_corpus_admin reads as a single role string. We
     * fall back to the first entry of a multi-valued {@code roles} claim for
     * tokens shaped that way (the user store keeps roles as a list). If neither
     * claim is present the header is omitted and the downstream fails closed
     * (require_corpus_admin → 401 on blank role).
     */
    private static String resolveRole(Jwt jwt) {
        String role = jwt.getClaimAsString("role");
        if (role != null && !role.isBlank()) {
            return role;
        }
        List<String> roles = jwt.getClaimAsStringList("roles");
        if (roles != null && !roles.isEmpty()) {
            return roles.get(0);
        }
        return null;
    }

    /**
     * Resolve a human-readable display name for the audit/HITL trail. Prefers
     * the OIDC {@code preferred_username} claim, falling back to {@code name}.
     * Display name is optional downstream (ingestion treats it as best-effort
     * provenance), so omitting the header when neither claim exists is safe.
     */
    private static String resolveUserName(Jwt jwt) {
        String preferred = jwt.getClaimAsString("preferred_username");
        if (preferred != null && !preferred.isBlank()) {
            return preferred;
        }
        return jwt.getClaimAsString("name");
    }

    @Override
    public int getOrder() {
        // Must run after Spring Security (the SecurityWebFilterChain runs ahead
        // of every GlobalFilter, so the principal / JwtAuthenticationToken is
        // already resolvable via exchange.getPrincipal()) but STRICTLY BEFORE
        // the routing filters that forward the request downstream —
        // NettyRoutingFilter and ForwardRoutingFilter both sit at
        // Ordered.LOWEST_PRECEDENCE. Returning LOWEST_PRECEDENCE here would tie
        // those orders, leaving the relative execution registration-order
        // dependent; if routing won, the asserted identity headers would be
        // mutated onto the request only after it had already been sent, so they
        // would never reach the downstream service. Ordering one slot earlier
        // guarantees the header mutation happens before the request is routed.
        // getPrincipal() is resolved lazily within filter(), so this earlier
        // order does not affect the JWT lookup.
        return Ordered.LOWEST_PRECEDENCE - 1;
    }
}
