# Capstone AWS deployment

- Deploy to the Blank Canvas AWS account `242925688392` in `ap-northeast-2` (Seoul).
- For local AWS operations, use the `archreactor-new` profile explicitly. Do not fall back to `default` or `peakle`.
- Verify the caller account with STS before changing AWS resources. Stop if it does not match `242925688392`.
- Exception: use `archreactor-management` (verify account `731732399204`) only for authorized Organizations policy administration. The approved Seoul exception applies exclusively to Blank Canvas; deploy all workload resources to `242925688392`.
- The AWS Agent Toolkit and AWS MCP endpoint use `us-east-1`; this does not change the deployment region.
- Follow `docs/aws/beanstalk.md` for the backend deployment configuration.

<!-- BEGIN AWS AGENT TOOLKIT GUIDANCE -->
# AWS Guidance

- Where these AWS rules conflict with the project's own instructions, the
  project's instructions take precedence.
- Prefer the AWS MCP Server for AWS interactions — it provides sandboxed
  execution, observability, and audit logging. If unavailable, use the
  AWS CLI directly.
- Before starting a task, check whether a relevant AWS skill is available.
  Load the skill with `retrieve_skill` and prefer its guidance over
  general knowledge.
- When uncertain about specific AWS details (API parameters, permissions,
  limits, error codes), verify against documentation rather than guessing.
  State uncertainty explicitly if you cannot confirm.
- When creating infrastructure, prefer infrastructure-as-code (AWS CDK or
  CloudFormation) over direct CLI commands.
- When working with infrastructure, follow AWS Well-Architected Framework
  principles.
- Do not use em dashes in AWS resource names or descriptions. Use
  hyphens instead.

## Secret Safety

- MUST load the `aws-secrets-manager` skill first for any secret,
  credential, API key, token, or password task. MUST NOT call
  `secretsmanager get-secret-value` or `batch-get-secret-value`, and MUST
  NOT hit the Secrets Manager Agent daemon directly. MUST use
  `{{resolve:secretsmanager:secret-id:SecretString:json-key}}` with
  `asm-exec` so the secret resolves at runtime without entering context.
<!-- END AWS AGENT TOOLKIT GUIDANCE -->
