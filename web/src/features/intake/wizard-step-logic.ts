/**
 * Six-step new-run wizard: when「下一步」may advance from the current step.
 *
 * Without these gates, Playwright (and fast clicks) can skip a step while its
 * panel is still loading — the target control never mounts on the active step.
 */
import type { ArtifactCard } from '@/features/intake/task-artifacts-logic';

export function taskStepReady(taskId: string | null, cards: ArtifactCard[], cardsPending: boolean): boolean {
  if (taskId === null) return false;
  if (cardsPending) return false;
  if (cards.length === 0) return false;
  return cards.every((card) => card.state === 'pass');
}

export function targetStepReady(
  serversPending: boolean,
  serversErrored: boolean,
  serverProfileId: string | null,
): boolean {
  if (serversPending || serversErrored) return false;
  return serverProfileId !== null;
}

export function intensityStepReady(
  presetsPending: boolean,
  presetsErrored: boolean,
  presetCount: number,
): boolean {
  if (presetsPending || presetsErrored) return false;
  return presetCount > 0;
}

export function canAdvanceFromWizardStep(
  stepIndex: number,
  ctx: {
    taskId: string | null;
    cards: ArtifactCard[];
    cardsPending: boolean;
    serversPending: boolean;
    serversErrored: boolean;
    serverProfileId: string | null;
    presetsPending: boolean;
    presetsErrored: boolean;
    presetCount: number;
  },
): boolean {
  switch (stepIndex) {
    case 0:
      return taskStepReady(ctx.taskId, ctx.cards, ctx.cardsPending);
    case 1:
      return targetStepReady(ctx.serversPending, ctx.serversErrored, ctx.serverProfileId);
    case 2:
      return true;
    case 3:
      return intensityStepReady(ctx.presetsPending, ctx.presetsErrored, ctx.presetCount);
    case 4:
      return true;
    default:
      return false;
  }
}
