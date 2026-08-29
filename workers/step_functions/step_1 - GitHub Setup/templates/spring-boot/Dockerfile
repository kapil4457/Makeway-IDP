FROM eclipse-temurin:21-jre-alpine

WORKDIR /app

COPY target/makeway-spring-service-0.1.0.jar app.jar

ARG SERVICE_NAME=__SERVICE_NAME__
ENV SERVICE_NAME=${SERVICE_NAME}

EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]