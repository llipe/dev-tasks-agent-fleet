/**
 * The AgentCore constructs find `agentcore/` by walking up from INIT_CWD (or the
 * cwd). Under `pnpm --dir agents/code-review/agentcore/cdk test` INIT_CWD is the
 * repository root, so pin the project root explicitly for every suite.
 */
import * as path from 'path';
import { setSessionProjectRoot } from '@aws/agentcore-cdk';

setSessionProjectRoot(path.resolve(__dirname, '..', '..', '..'));
