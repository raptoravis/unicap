# Graph Report - .  (2026-04-28)

## Corpus Check
- Corpus is ~2,641 words - fits in a single context window. You may not need a graph.

## Summary
- 42 nodes · 53 edges · 6 communities detected
- Extraction: 92% EXTRACTED · 8% INFERRED · 0% AMBIGUOUS · INFERRED: 4 edges (avg confidence: 0.82)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Three Keys & Alignment|Three Keys & Alignment]]
- [[_COMMUNITY_Engineering Discipline Skills|Engineering Discipline Skills]]
- [[_COMMUNITY_Multi-Agent Scaling Handbook|Multi-Agent Scaling Handbook]]
- [[_COMMUNITY_Parallelization Modes|Parallelization Modes]]
- [[_COMMUNITY_TPDD & Event Contract|TPDD & Event Contract]]
- [[_COMMUNITY_Testing & Safety Invariants|Testing & Safety Invariants]]

## God Nodes (most connected - your core abstractions)
1. `Multi-Agent Parallel Development Handbook` - 12 edges
2. `.claude/skills/ Directory` - 10 edges
3. `Four Parallelization Modes` - 5 edges
4. `Three Keys Framework` - 4 edges
5. `TPDD (Test Plan-Driven Development)` - 4 edges
6. `Mode 2: Same Project, Different Modules (git worktree)` - 4 edges
7. `Sponsor Profile (Human Engineer)` - 4 edges
8. `Risk Module (风控模块)` - 4 edges
9. `Multi-Layer Testing Strategy` - 4 edges
10. `工程纪律 Skill 化 (Engineering Discipline as Skills)` - 3 edges

## Surprising Connections (you probably didn't know these)
- `需求对齐 (Requirement Alignment)` --semantically_similar_to--> `Decision Style: Top 3 Options`  [INFERRED] [semantically similar]
  docs/methodology.md → USER.md
- `Zero-Review Paradigm` --semantically_similar_to--> `工程纪律 Skill 化 (Engineering Discipline as Skills)`  [INFERRED] [semantically similar]
  USER.md → docs/methodology.md
- `unicap.git Repository` --references--> `Multi-Agent Parallel Development Handbook`  [EXTRACTED]
  CLAUDE.md → docs/methodology.md
- `Multi-Agent Parallel Development Handbook` --implements--> `Three Keys Framework`  [EXTRACTED]
  docs/methodology.md → CLAUDE.md
- `Three Keys Framework` --implements--> `TPDD (Test Plan-Driven Development)`  [EXTRACTED]
  CLAUDE.md → docs/methodology.md

## Hyperedges (group relationships)
- **Three Keys Resolving the Three Bottlenecks** — claude_requirement_alignment, claude_tpdd, claude_engineering_skills [EXTRACTED 0.95]
- **Skill Library Enforcing Agent Engineering Discipline at Startup** — claude_skills_dir, claude_engineering_skills, methodology_claude_code [INFERRED 0.85]
- **Parallel Worktrees Coordinated via Frozen Event Contract** — claude_mode2_different_modules, claude_events_contract, claude_git_worktree [EXTRACTED 0.92]

## Communities

### Community 0 - "Three Keys & Alignment"
Cohesion: 0.29
Nodes (8): 工程纪律 Skill 化 (Engineering Discipline as Skills), unicap.git Repository, 需求对齐 (Requirement Alignment), Sponsor Profile (Human Engineer), Three Keys Framework, Chinese Summary Requirement, Decision Style: Top 3 Options, Zero-Review Paradigm

### Community 1 - "Engineering Discipline Skills"
Cohesion: 0.25
Nodes (8): PR and Merge Rules, error-policy.md Skill, info-hiding.md Skill, module-depth.md Skill, naming.md Skill, pr-summary.md Skill, .claude/skills/ Directory, Structured PR Summary Template

### Community 2 - "Multi-Agent Scaling Handbook"
Cohesion: 0.29
Nodes (8): Multi-Agent Parallel Development Handbook, Agent Capacity Formula, Claude Code (Opus 4.7 / Sonnet 4.6), Common Pitfalls (九、常见陷阱), Onboarding Ramp (W1-W5+ Schedule), atum.li 'How to Scale AI Dev' (2026 Spring), Three Gates for Multi-Agent Readiness, Typical Weekly Rhythm (3-person + 5-Agent Team)

### Community 3 - "Parallelization Modes"
Cohesion: 0.33
Nodes (7): Four Parallelization Modes, git worktree, Mode 1: Cross-Project Parallelization, Mode 2: Same Project, Different Modules (git worktree), Mode 3: Same Module, Different Transaction Types, Mode 4: Intra-Task Sub-Module Parallelization, Multi-Path Parallel Attempts (择优合并)

### Community 4 - "TPDD & Event Contract"
Cohesion: 0.33
Nodes (6): Event Contract (events.*), events-frozen.md Skill, tpdd.md Skill, TPDD (Test Plan-Driven Development), Risk Module (风控模块), Programmatic Stock Trading System (Example Project)

### Community 5 - "Testing & Safety Invariants"
Cohesion: 0.4
Nodes (5): invariants.md Skill, replay-suite.md Skill, Capital/Fund Invariants, Historical Replay Testing, Multi-Layer Testing Strategy

## Knowledge Gaps
- **14 isolated node(s):** `Mode 1: Cross-Project Parallelization`, `Mode 4: Intra-Task Sub-Module Parallelization`, `naming.md Skill`, `module-depth.md Skill`, `info-hiding.md Skill` (+9 more)
  These have ≤1 connection - possible missing edges or undocumented components.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Multi-Agent Parallel Development Handbook` connect `Multi-Agent Scaling Handbook` to `Three Keys & Alignment`, `Parallelization Modes`, `TPDD & Event Contract`, `Testing & Safety Invariants`?**
  _High betweenness centrality (0.504) - this node is a cross-community bridge._
- **Why does `.claude/skills/ Directory` connect `Engineering Discipline Skills` to `Three Keys & Alignment`, `TPDD & Event Contract`, `Testing & Safety Invariants`?**
  _High betweenness centrality (0.382) - this node is a cross-community bridge._
- **Why does `Three Keys Framework` connect `Three Keys & Alignment` to `Multi-Agent Scaling Handbook`, `TPDD & Event Contract`?**
  _High betweenness centrality (0.228) - this node is a cross-community bridge._
- **What connects `Mode 1: Cross-Project Parallelization`, `Mode 4: Intra-Task Sub-Module Parallelization`, `naming.md Skill` to the rest of the system?**
  _14 weakly-connected nodes found - possible documentation gaps or missing edges._