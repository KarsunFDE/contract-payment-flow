package com.karsunfde.contractflow.gateway;

import java.util.List;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.web.reactive.EnableWebFluxSecurity;
import org.springframework.security.config.web.server.ServerHttpSecurity;
import org.springframework.security.web.server.SecurityWebFilterChain;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.reactive.CorsConfigurationSource;
import org.springframework.web.cors.reactive.UrlBasedCorsConfigurationSource;

/**
 * Reactive security configuration for the API Gateway.
 *
 * ⚠ DELIBERATE BROWNFIELD DEBT — Item 1 in docs/brownfield-debt.md ⚠
 *
 * The gateway exposes a /api/public/** path that is intended for unauthenticated
 * "public" reads (e.g., catalog browsing). But the route is also wired so that
 * any JWT presented on that path is accepted WITHOUT signature verification:
 * {@link JwtSignatureSkipFilter} short-circuits the standard
 * spring-security-oauth2-resource-server validator.
 *
 * In practice this means a caller can mint a JWT with any claims (including
 * elevated roles) and have it accepted as long as it's structurally a JWT —
 * because the public path's filter accepts it without checking the signature,
 * and downstream services trust the upstream "this gateway already validated"
 * convention.
 *
 * Cohort finds this in W1 Tue brownfield-debt inventory; fix lands in W4 Wed
 * AI Security Engineering Day (OWASP LLM07/08 — tool-misuse prevention).
 *
 * What "fixed" looks like:
 *   - Delete {@link JwtSignatureSkipFilter}.
 *   - Route /api/public/** through the standard oauth2 resource-server JWT
 *     decoder (signature MUST verify against the JWKS).
 *   - Use {@code authorizeExchange().pathMatchers("/api/public/**").permitAll()}
 *     only for genuinely-anonymous reads; never for paths that resolve a user
 *     identity.
 */
@Configuration
@EnableWebFluxSecurity
public class SecurityConfig {

    /**
     * DEV-ONLY escape hatch. The local stack runs no OIDC issuer (JWT_ISSUER_URI
     * points at a mock that isn't started), so the Angular SPA cannot obtain a
     * real token and every authenticated route 401s. When this flag is true we
     * permit the application's data routes through the gateway and enable CORS
     * for the local SPA origin — so all SPA traffic still routes THROUGH the
     * gateway (no service-URL hardcode; cf. Item 8) without a dev auth server.
     *
     * Defaults to false: production keeps {@code anyExchange().authenticated()}.
     * This does NOT touch the Item 1 signature-skip path below.
     */
    @Value("${gateway.dev-no-auth:false}")
    private boolean devNoAuth;

    @Bean
    public SecurityWebFilterChain springSecurityFilterChain(ServerHttpSecurity http) {
        http
            .csrf(csrf -> csrf.disable())
            // CORS preflight (OPTIONS) is handled here, ahead of auth, so the
            // browser pre-flight to the gateway succeeds in dev. No-op unless the
            // corsConfigurationSource bean is present (dev-no-auth only).
            .cors(cors -> {})
            .authorizeExchange(exchanges -> {
                exchanges.pathMatchers("/actuator/**").permitAll();
                // ↓↓↓ ITEM 1 — the public route bypasses real auth.
                exchanges.pathMatchers("/api/public/**").permitAll();
                if (devNoAuth) {
                    // DEV-ONLY: no OIDC issuer locally — permit the SPA's data
                    // routes so they reach the (permitAll) downstream services.
                    exchanges.pathMatchers(
                        "/api/contract-modifications/**",
                        "/api/invoice-reviews/**").permitAll();
                }
                exchanges.anyExchange().authenticated();
            })
            .oauth2ResourceServer(oauth2 -> oauth2.jwt(jwt -> {}))
            // ↓↓↓ ITEM 1 — the skip filter accepts unsigned JWTs on /api/public/**.
            .addFilterBefore(new JwtSignatureSkipFilter(),
                org.springframework.security.config.web.server.SecurityWebFiltersOrder.AUTHENTICATION);

        return http.build();
    }

    /**
     * DEV-ONLY CORS for the local Angular origin. Only created when
     * gateway.dev-no-auth=true, so production exposes no cross-origin allowance
     * here (prod serves the SPA same-origin / behind the edge).
     */
    @Bean
    @ConditionalOnProperty(name = "gateway.dev-no-auth", havingValue = "true")
    public CorsConfigurationSource corsConfigurationSource() {
        CorsConfiguration cfg = new CorsConfiguration();
        cfg.setAllowedOrigins(List.of("http://localhost:4200", "http://localhost"));
        cfg.setAllowedMethods(List.of("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"));
        cfg.setAllowedHeaders(List.of("*"));
        UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();
        source.registerCorsConfiguration("/**", cfg);
        return source;
    }
}
