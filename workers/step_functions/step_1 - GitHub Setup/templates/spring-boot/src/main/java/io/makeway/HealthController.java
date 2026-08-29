package io.makeway;

import java.util.Map;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

/** Simple root + health endpoints so the golden-path service is immediately verifiable. */
@RestController
public class HealthController {

    @Value("${service.name:__SERVICE_NAME__}")
    private String serviceName;

    @GetMapping("/")
    public Map<String, String> root() {
        return Map.of("service", serviceName, "status", "ok");
    }

    @GetMapping("/health")
    public Map<String, String> health() {
        return Map.of("status", "healthy");
    }
}