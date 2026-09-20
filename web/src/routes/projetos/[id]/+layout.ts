import { error } from '@sveltejs/kit';
import { ApiError, api } from '$lib/api';
import type { LayoutLoad } from './$types';

export const load: LayoutLoad = async ({ params }) => {
  try {
    return { project: await api.getProject(params.id) };
  } catch (e) {
    if (e instanceof ApiError) error(e.status || 500, e.message);
    throw e;
  }
};
