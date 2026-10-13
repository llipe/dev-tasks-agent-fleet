/**
 * Icon set — /DESIGN.md §10.
 *
 * The prototype used Unicode glyph stand-ins (▦ ≡ ⑃ ⚙ ◈ « » › ✕). §10 replaces
 * every one with a Phosphor icon rendered as inline SVG on `currentColor`.
 * This module maps each semantic role to its Phosphor equivalent so the rest
 * of the app imports by intent (`<AgentsIcon />`) rather than by Phosphor name,
 * and no Unicode stand-in survives.
 *
 * Imported from `@phosphor-icons/react/ssr`: the package's default entry is
 * marked "use client", but these icons are purely presentational and must be
 * usable inside Server Components (Breadcrumb, pages), so the SSR build is the
 * correct entrypoint. Phosphor icons inherit `currentColor` by default, so the
 * icon color follows the surrounding text color (§10 requirement).
 */
import {
  GridFour,
  List,
  GitBranch,
  GearSix,
  Heartbeat,
  CaretLeft,
  CaretRight,
  CaretDown,
  Power,
  X,
  CalendarDots,
  Bell,
  Plus,
  Pause,
  Play,
  Pencil,
  Trash,
  GitPullRequest,
  Warning,
  SkipForward,
  LockSimple,
} from "@phosphor-icons/react/ssr";
import type { IconProps } from "@phosphor-icons/react";

export type { IconProps };

// §10 mapping table, by semantic role.
export const AgentsIcon = GridFour; // ▦ Agents
export const AllRunsIcon = List; // ≡ All runs
export const RepositoriesIcon = GitBranch; // ⑃ Repositories
export const SettingsIcon = GearSix; // ⚙ Settings
export const SystemHealthIcon = Heartbeat; // ◈ System health
export const CollapseIcon = CaretLeft; // « Collapse
export const ExpandIcon = CaretRight; // » Expand
export const RowChevronIcon = CaretRight; // › Row chevron
export const LogOutIcon = Power; // ⏻ Log out (S-120)
export const CloseIcon = X; // ✕ Close

// §10 Phase 4 — Agent Scheduler + Notifications (S-161..S-164).
export const SchedulesIcon = CalendarDots; // Schedules nav + agent indicator
export const NotificationsIcon = Bell; // Notifications nav + top-bar bell
export const NewScheduleIcon = Plus; // New schedule button
export const PauseIcon = Pause; // Pause action
export const PlayIcon = Play; // Resume action
export const EditIcon = Pencil; // Edit action
export const DeleteIcon = Trash; // Delete action
export const OpenPrIcon = GitPullRequest; // open_pr reason chip
export const WarningIcon = Warning; // auto_paused reason chip
export const SkipIcon = SkipForward; // concurrency_cap / missed_tick reason chip
export const LockIcon = LockSimple; // always-on guardrail lines
export const CaretDownIcon = CaretDown; // disclosure open
export const CaretRightIcon = CaretRight; // disclosure closed
