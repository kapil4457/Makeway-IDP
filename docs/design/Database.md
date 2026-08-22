# Forge — Database Schema

**Database:** PostgreSQL (single instance). Relational data with heavy joins across Apps/Environments/Services/Capabilities/Jobs `jsonb` columns used for variable-shape fields (config, output, raw payloads).

---

## Team

Organizational team that owns apps.

```
teamId (PK)
teamName
createdAt / createdBy
modifiedAt / modifiedBy
```

**Why:** Ownership root for Apps and permissions.

---

## User

Individual developer using Forge.

```
userId (PK)
email (unique)
createdAt / createdBy
modifiedAt / modifiedBy
```

**Why:** Referenced by `createdBy`/`modifiedBy` across all tables; auth and RBAC.

---

## TeamMember

Join table: Team ↔ User.

```
teamMemberId (PK)
teamId (FK → Team)
userId (FK → User)
role [owner, member]
isDeleted (boolean, default false)
joinedAt
UNIQUE (teamId, userId)
```

**Why:** Users can belong to multiple teams. `isDeleted` preserves audit
history when a user leaves a team instead of losing the record.

---

## App

Top-level unit Forge manages. One App = one GitHub monorepo.

```
appId (PK)
appName
teamId (FK → Team)
repoUrl
createdAt / createdBy
modifiedAt / modifiedBy
```

**Why:** Anchor entity. All Environments, Services, and Requests trace back to it.

---

## Cluster

Static reference data for the 3 fixed EKS clusters.

```
clusterId (PK)
clusterName
kubeApiEndpoint
```

**Why:** `Namespace` and `Environment` need a stable FK target identifying which physical EKS cluster to deploy to. Reference data thus no audit fields, seeded once, not app-managed.

---

## Environment

A deployment environment (dev/qa/uat/prod) belonging to an App.

```
envId (PK)
appId (FK → App)
envName [dev, qa, uat, prod]
clusterId (FK → Cluster)
createdAt / createdBy
modifiedAt / modifiedBy
UNIQUE (appId, envName)
```

**Why:** Capabilities and deployments are tracked per environment, not per app. Same App can be READY in dev and FAILED in prod simultaneously. `clusterId` maps each environment to its physical cluster.

---

## Service

One deployable unit inside an App's monorepo.

```
serviceId (PK)
appId (FK → App)
serviceName
serviceType [spring-boot, fastapi, nodejs]
repoPath
createdAt / createdBy
modifiedAt / modifiedBy
UNIQUE (appId, serviceName)
```

**Why:** Monorepo apps contain multiple services; Capabilities, Namespaces, and DeploymentSetup all scope to a specific service.

---

## Namespace

Kubernetes namespace for a Service in an Environment.

```
namespaceId (PK)
serviceId (FK → Service)
envId (FK → Environment)
clusterId (FK → Cluster)
k8sNamespaceName (unique per cluster)
status [PENDING, IN_PROGRESS, SUCCESS, FAILED]
createdAt / modifiedAt
UNIQUE (serviceId, envId)
```

**Why:** Tracks the actual K8s namespace backing each service+environment pair, and which cluster it lives on.

---

## Capability

Requested infrastructure (database, cache, queue, etc.), scoped to an environment and optionally a service.

```
capabilityId (PK)
envId (FK → Environment)
serviceId (FK → Service, nullable)   -- null = app-wide/shared
capabilityType [database, cache, queue, notification, storage, cdn]
status [PENDING, IN_PROGRESS, SUCCESS, FAILED, PARTIALLY_FAILED]
errorMessage (nullable)
createdAt / createdBy
modifiedAt / modifiedBy
```

**Why:** Core unit of "what infra does this app need, and is it ready," per environment. `serviceId` nullable to support both service-bound and app-shared resources.

---

## InfraRequirement

Configuration and provisioning output for a Capability.

```
infraRequirementId (PK)
capabilityId (FK → Capability)
config (jsonb)               -- storageGb, ttl, tier, replicas, etc.
secretRef (text, nullable)   -- Secrets Manager ARN/path only, never the value
outputRef (jsonb, nullable)  -- endpoint, URL, ARN, bucket name, etc.
createdAt / modifiedAt
```

**Why:** Separates input config from provisioning output. `jsonb` avoids schema changes per capability type. `secretRef`/`outputRef` split enforces credentials never land in plain columns.

---

## AccessBinding

IAM grant linking a Service to a Capability within a Namespace.

```
accessBindingId (PK)
capabilityId (FK → Capability)
serviceId (FK → Service)
namespaceId (FK → Namespace)
roleArn
accessType [READ, WRITE, READ_WRITE]
createdAt / modifiedAt
UNIQUE (capabilityId, serviceId, namespaceId)
```

**Why:** Explicit, auditable access grant per (capability, service, namespace). A service has no access to a capability. It is shared or bound, unless a row exists here. This is what enforces "shared vs. "bound" resource access at the IAM layer.

---

## NetworkIsolationRule

Tracks applied network-level isolation for a Namespace.

```
ruleId (PK)
namespaceId (FK → Namespace)
ruleType [K8S_NETWORK_POLICY, SECURITY_GROUP]
targetRef (text)              -- policy name or security group ID
status
createdAt / modifiedAt
```

**Why:** Visibility into whether NetworkPolicy/Security Group isolation was actually applied for a namespace as namespaces alone don't isolate network traffic; this tracks the enforcement layer that does.

---

## DeploymentSetup

ArgoCD registration and sync status for a Service in an Environment.

```
deploymentSetupId (PK)
serviceId (FK → Service)
envId (FK → Environment)
status [PENDING, IN_PROGRESS, SUCCESS, FAILED]
argocdAppName (nullable)
lastSyncedAt (nullable)
errorMessage (nullable)
createdAt / modifiedAt
UNIQUE (serviceId, envId)
```

**Why:** Deployment mechanism, not an infra resource thus kept separate from Capability. `envId` required since a service deploys independently to each environment with independent sync state.

---

## Request

A single user-initiated action.

```
requestId (PK)
idempotencyKey (unique)
requestType [CREATE_APP, ADD_CAPABILITY, DELETE_CAPABILITY, DELETE_APP, UPDATE_RESOURCE, UPDATE_APP]
appId (FK → App, nullable)
requestStatus [PENDING, IN_PROGRESS, SUCCESS, FAILED, PARTIALLY_FAILED]
rawRequest (jsonb)
createdAt / createdBy
modifiedAt / modifiedBy
```

**Why:** `idempotencyKey` prevents duplicate submission from creating duplicate infra.

---

## Job

A single async execution attempt from the queue.

```
jobId (PK)
requestId (FK → Request)
capabilityId (FK → Capability, nullable)
deploymentSetupId (FK → DeploymentSetup, nullable)
step [CREATE_PROJECT, PROVISION_INFRA, ARGOCD_SETUP]
status [PENDING, IN_PROGRESS, SUCCESS, FAILED]
stepFunctionExecutionArn (text)
errorDetail (text, nullable)
startedAt / completedAt
```

**Why:** Tracks retry history, per-attempt errors, and queue traceability — required for idempotent retries and debugging stuck/failed steps.

---

## Entity Relationships

```
Team ──< TeamMember >── User
Team ──< App
App ──< Environment >── Cluster
App ──< Service
Environment ──< Namespace >── Service, Cluster
Environment ──< Capability >── Service (nullable)
Capability ──< InfraRequirement (1:1)
Capability ──< AccessBinding >── Service, Namespace
Namespace ──< NetworkIsolationRule
Service ──< DeploymentSetup >── Environment
App ──< Request
Request ──< Job >── Capability (nullable), DeploymentSetup (nullable)
```