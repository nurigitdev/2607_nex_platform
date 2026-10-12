# PLAT-CP08 AE-WEB / IA / Notification Contracts

- AE-WEB is a presentation surface; IA is a runtime Agent type.
- User Prompt -> AE-API -> IA PROMPT execution.
- Notification is a projection, not Work/Approval/Runtime authority.
- HumanActionView distinguishes HUMAN_CONFIRMATION / AGENT_FORMAL / NSL_WRITE / STEP_UP.
- PA project status is a projection over AE/WC-owned state.

- NotificationView state (UNREAD/READ/HANDLED) is presentation state and is not ResultDelivery ACK state.
- Notification may carry AgentResult/ResultDelivery/PublicationOperation refs for trace/deep-link only.
- Durable Workspace Result is completion-critical for IA; notification/email/messenger fan-out is optional asynchronous publication.
