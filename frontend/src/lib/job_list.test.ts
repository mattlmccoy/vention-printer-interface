import { test } from "node:test";
import assert from "node:assert/strict";
import { splitArchived } from "./job_list.ts";

const j = (name: string, archived?: boolean) => ({ name, path: `/h/${name}`, archived });

test("splitArchived keeps order and separates archived jobs", () => {
  const { active, archived } = splitArchived([j("a"), j("b", true), j("c", false), j("d", true)]);
  assert.deepEqual(active.map((x) => x.name), ["a", "c"]);
  assert.deepEqual(archived.map((x) => x.name), ["b", "d"]);
});

test("the archived section opens by itself when the selected job is archived", () => {
  const jobs = [j("a"), j("b", true)];
  assert.equal(splitArchived(jobs, "/h/b").selectedIsArchived, true);
  assert.equal(splitArchived(jobs, "/h/a").selectedIsArchived, false);
  assert.equal(splitArchived(jobs, null).selectedIsArchived, false);
});
