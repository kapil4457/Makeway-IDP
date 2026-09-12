"""Update payload for an existing app.

The update endpoint takes a bare JSON **list** of per-environment updates —
``[{env, services?, capabilities?}]`` — expressed as a **delta**: each entry
states the desired state for the capabilities/services it mentions, and
anything not mentioned stays untouched. Removal is deliberately not
expressible (teardown is out of scope).

The element schema is the create flow's own ``EnvConfig`` (services +
discriminated capability configs), so what an update may ask for is exactly
what the app could have been created with — one schema, one validation path.
"""
from dto.configs.env_config import EnvConfig

# One per-environment update. Reusing EnvConfig keeps the update surface
# byte-compatible with create; delta semantics are enforced by the service.
AppEnvUpdate = EnvConfig