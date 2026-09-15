# ---- build stage: Maven + JDK 21 (matches the pom's java.version) ----------
FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /src
COPY pom.xml .
# Best-effort dependency warm-up: source edits then reuse the cached dep layer.
RUN mvn -q -B -DskipTests dependency:go-offline || true
COPY src ./src
RUN mvn -q -B -DskipTests package

# ---- runtime stage ----------------------------------------------------------
FROM eclipse-temurin:21-jre-alpine
WORKDIR /app
# spring-boot repackage replaces the artifact jar in place, so exactly one
# *.jar lands in target/ — the glob survives version bumps (no hardcoded
# makeway-spring-service-0.1.0).
COPY --from=build /src/target/*.jar app.jar

ARG SERVICE_NAME=__SERVICE_NAME__
ENV SERVICE_NAME=${SERVICE_NAME}

EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
