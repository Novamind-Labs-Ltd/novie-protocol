# novie-protocol

The **only allowed shared dependency** between the platform and expert Agents.

| Subpackage | Contents |
|---|---|
| `contracts/` | `ExecutionContext` / `TenantScope` / `IdentityContext` / `TaskBrief` / `ExecutionPlan` / `ExecutionStep` / `GateSpec` / `PolicyRequest` / `PolicyDecision` / `CheckpointSnapshot` |
| `services/` | `PlatformServices` and Service Protocols (`WikiService` / `ReviewService` / `PolicyService` / `CheckpointService` / `TimeTravelService` / `EventBus`) |
| `agents/`   | `ExpertAgent` Protocol and `AgentCard` descriptor |
| `events/`   | `SessionEventChannel` and SSE/JSON event schemas |

Design constraints are in `ARCHITECTURE.md` §15 and Appendix A. **Do not** put any business implementation in this package.
