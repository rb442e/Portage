# Poteto-mode: From intent to evidence

An original narrated visual explanation of Lauren Tan’s installed pstack 0.15.30 instructions. This is an illustrated explainer, not a recording of an agent implementing OAuth. Narration uses synthetic speech. Interpretations of author intent are labeled as interpretations.

## 0:00 · THE BIG IDEA

Imagine giving an engineer a short request, and also handing them your team's engineering handbook. That is a useful way to understand poteto mode. In this film, we will unpack Lauren Tan's skill file, then follow an illustrated Portage feature from a user's intention to evidence that it works.

**On-screen takeaway:** You provide the outcome. The skill supplies a disciplined approach.

## 0:19 · 01 / THE INTENTION

The file describes Lauren's preferred engineering style. Read the system before changing it. Choose clear structures. Keep the code and explanation simple. Delegate deliberately, and verify the outcome. My interpretation is that she wants these habits to become repeatable, so an agent can carry more of the engineering work while leaving evidence that a person can review.

**On-screen takeaway:** The ambition is reliable judgment, supported by observable work.

## 0:41 · 02 / INSIDE SKILL.MD

Open skill dot M D and you will find several layers. Metadata identifies the skill. Triggers connect situations to other skills. Principles guide decisions. Playbooks organize different tasks, such as features, bug fixes, and investigations. This is instruction text read by an agent. It is not an executable engine that automatically forces every step to happen.

**On-screen takeaway:** A Markdown skill gives instructions. Codex still performs the actions.

## 1:05 · 03 / ONE REQUEST, ONE WORKFLOW

Suppose you ask, use poteto mode to add OAuth for remote MCP servers in Portage. The agent recognizes a feature request and reads the feature playbook. A broken connection would instead call for a bug fix. A question about how authentication works would call for an investigation. The mode coordinates the relevant workflow. It does not run every skill for every request.

**On-screen takeaway:** A feature, a bug, and a question need different workflows.

## 1:29 · 04 / UNDERSTAND BEFORE DESIGN

The how skill traces what the system actually does. For Portage, that means following settings, credential storage, MCP connections, and Sora tool calls. The why skill asks what led to that design, using history and available records. Why becomes especially relevant when ownership or layering changes. If the evidence is missing, the agent should say so rather than inventing the original intention.

**On-screen takeaway:** Use why when existing decisions matter. Do not invent their motivation.

## 1:54 · 05 / DESIGN WITH EVIDENCE

Next comes architecture. The architect skill uses arena to explore different designs and synthesize a choice. For OAuth, an illustrative comparison is SDK managed authentication versus application managed authentication. The agent should investigate actual support before choosing. The feature workflow then breaks delivery into verifiable units. A separate plan is not a universal skill. If you want to approve the design first, explicitly request that checkpoint.

**On-screen takeaway:** A separate design approval checkpoint must be requested explicitly.

## 2:24 · 06 / MODEL THE DOMAIN

One of the file's recurring ideas is to model the domain before filling in logic. In an OAuth example, disconnected, authorizing, connected, refreshing, and reconnect required are meaningful states. Making those transitions explicit can be clearer than scattering unrelated flags across the code. This diagram illustrates the principle. It does not claim that OAuth has already been implemented in Portage.

**On-screen takeaway:** A clear state model makes transitions and failure paths easier to reason about.

## 2:49 · 07 / DELEGATE DELIBERATELY

Poteto mode asks the lead agent to delegate focused work, then own the result. Investigators can inspect different areas. An implementation agent can work within a defined scope. A reviewer can challenge the result. Independent work may run in parallel, but shared changes need coordination. The exact agent types and model choices depend on the host. Installing the skill cannot create capabilities that Codex does not expose.

**On-screen takeaway:** The coordinator reviews and integrates. It remains accountable for the result.

## 3:16 · 08 / PROVE IT WORKS

Verification closes the loop. For Portage, our verify Portage driver launches an isolated instance, exercises behavior, and saves evidence. A successful connection is different from a successful tool call. A successful tool call is different from a correct answer. Reports should distinguish passed, failed, blocked, and review required. A green build alone cannot prove the complete user journey.

**On-screen takeaway:** A green build is one check. It does not establish that a user journey works.

## 3:42 · 09 / AUTONOMY WITH BOUNDARIES

The autonomy section encourages progress on authorized, reversible work. Its always pause section names consequential actions, including deployments, data deletion, customer messages, and force pushes to shared branches. Read these as workflow instructions within the host's actual permissions and your authorization. The skill cannot override those boundaries. Ask for an additional design checkpoint whenever you want to review a choice before implementation.

**On-screen takeaway:** Skill instructions never expand the host’s permissions or override its safety rules.

## 4:10 · 10 / WATCH THE WORK

How do you know the agent followed the workflow? Inspect the skill files it read, the tasks it delegated, the commands it ran, and the artifacts it produced. For long work, show me your work adds a decision trail. These are observable records, not access to private internal reasoning. If a tool, model, or workflow step is unavailable, the agent should disclose that limitation.

**On-screen takeaway:** A statement of compliance is not proof that the workflow was followed.

## 4:34 · 11 / YOUR PART OF THE CONTRACT

Your part is to state the goal, the finish line, the evidence, and the real constraints. For example, let users authorize a remote MCP server, then prove an authenticated tool call succeeds. Keep credentials out of logs, and let me review the design first. You do not need to prescribe every skill in sequence. Clear intent gives the playbook room to do its job.

**On-screen takeaway:** You own product intent and approval boundaries. The agent owns execution and evidence.

## 4:58 · POTETO MODE / THE TAKEAWAY

My reading of Lauren's intent is to turn strong engineering habits into reusable instructions, supported by tools that can prove outcomes. The human provides direction. The agent investigates, designs, implements, and verifies. Poteto mode supplies the playbook. The host supplies the capabilities. The evidence lets you assess the result. That is the useful idea to bring into Portage.

**On-screen takeaway:** Based on the installed pstack 0.15.30 skill. Original educational interpretation.

## Sources and scope

- Primary source: the installed `pstack/0.15.30/skills/poteto-mode/SKILL.md`.
- Public upstream: https://github.com/cursor/plugins/blob/main/pstack/skills/poteto-mode/SKILL.md
- Feature playbook: https://github.com/cursor/plugins/blob/main/pstack/skills/poteto-mode/playbooks/feature.md
- Architecture workflow: https://github.com/cursor/plugins/blob/main/pstack/skills/architect/SKILL.md
- Prompting guidance: https://github.com/cursor/plugins/blob/main/pstack/skills/poteto-help/references/prompting.md
- Upstream pstack is MIT licensed, Copyright (c) 2026 Lauren Tan. The visuals and narration are original paraphrase and interpretation.

The explanation illustrates workflow intent; it does not establish exact behavior across all agent hosts. Cursor-specific agents, models, and persistent modes may not be available in Codex. The user’s authorization and the host’s actual permissions govern execution. The OAuth states and alternatives are conceptual, not implemented Portage functionality.

## Playback and reproduction

The MP4 includes 13 chapter markers and an optional English subtitle track. Separate captions are in `Poteto_Mode_Explained.srt`. Reproduce the recording with `demo/record_poteto_mode.py`; edit the original narration and scene content in `demo/poteto_mode_scenes.json`. The animated layout is `demo/poteto_mode_explainer.html`. The provenance manifest records the source skill hash and export validation.

Upstream license: https://github.com/cursor/plugins/blob/main/pstack/LICENSE
