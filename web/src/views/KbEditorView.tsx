import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import {
  ApiError,
  createKbEntry,
  fetchKbEntries,
  fetchKbEntry,
  fetchKbTypes,
  publishKbEntry,
  updateKbEntry,
  type KbEntryInput,
} from "../api/client";
import { repoList, useAppStore } from "../store";
import {
  Button,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
} from "../ui";
import styles from "./KbEditorView.module.css";
import viewFrameStyles from "./viewFrame.module.css";

const GLOBAL = "__global__";
const PUBLISHED_LIMIT = 500; // the API maximum

interface FormState {
  type: string;
  slug: string;
  title: string;
  body: string;
  aliases: string;
  payload: string;
  repository: string;
}

const EMPTY: FormState = {
  type: "glossary",
  slug: "",
  title: "",
  body: "",
  aliases: "",
  payload: "{}",
  repository: GLOBAL,
};

export default function KbEditorView() {
  const { entryId } = useParams();
  const editing = entryId !== undefined;
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const repo = useAppStore((state) => state.repo);

  const [form, setForm] = useState<FormState>(EMPTY);
  const [payloadError, setPayloadError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  const types = useQuery({
    queryKey: ["kb", "types"],
    queryFn: fetchKbTypes,
    staleTime: 5 * 60_000,
  });

  // Published entries of this type, so publishing a revision can pass the id
  // of the entry it replaces instead of dead-ending on a 409.
  const live = useQuery({
    queryKey: ["kb", "entries", { status: "published", repo, limit: PUBLISHED_LIMIT }],
    queryFn: () =>
      fetchKbEntries({
        status: "published",
        repo: repo ?? undefined,
        limit: PUBLISHED_LIMIT,
      }),
  });

  const existing = useQuery({
    queryKey: ["kb", "entry", entryId],
    queryFn: () => fetchKbEntry(Number(entryId)),
    enabled: editing,
  });

  // Hydrate from the server copy once. `repo` must NOT be a dependency: it
  // changes whenever the TopBar selector moves, and re-running this silently
  // reverted every field the human had edited.
  useEffect(() => {
    const entry = existing.data;
    if (!entry) return;
    setForm({
      type: entry.type,
      slug: entry.slug,
      title: entry.title,
      body: entry.body,
      aliases: (entry.aliases ?? []).join(", "),
      payload: JSON.stringify(entry.payload ?? {}, null, 2),
      // the entry's OWN scope, from the server — not the currently selected
      // repo, which is a guess and was wrong for any entry outside it
      repository: entry.repository ?? GLOBAL,
    });
  }, [existing.data]);

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  function buildInput(): KbEntryInput | null {
    let payload: Record<string, unknown>;
    try {
      payload = form.payload.trim() ? JSON.parse(form.payload) : {};
    } catch (parseError) {
      setPayloadError(`not valid JSON: ${String(parseError)}`);
      return null;
    }
    setPayloadError(null);
    const aliases = form.aliases
      .split(",")
      .map((alias) => alias.trim())
      .filter(Boolean);
    return {
      type: form.type,
      title: form.title,
      body: form.body,
      slug: form.slug || null,
      aliases: aliases.length > 0 ? aliases : null,
      payload,
      repository: form.repository === GLOBAL ? null : form.repository,
    };
  }

  const save = useMutation({
    mutationFn: async ({ input, publish }: { input: KbEntryInput; publish: boolean }) => {
      const entry = editing
        ? await updateKbEntry(Number(entryId), input)
        : // A new entry is a DRAFT unless the human asked to publish. Without
          // an explicit status the API defaults to "published", which made
          // "Save" and "Save & publish" the same button.
          await createKbEntry({ ...input, status: publish ? "published" : "proposed" });
      if (publish && entry.status !== "published") {
        // Publishing over a live entry needs its id, or the server 409s with
        // nothing in this form able to answer.
        return publishKbEntry(entry.id, incumbentId);
      }
      return entry;
    },
    onSuccess: (entry) => {
      queryClient.invalidateQueries({ queryKey: ["kb"] });
      navigate(`/kb?sel=${entry.id}`);
    },
    onError: (mutationError) => {
      if (mutationError instanceof ApiError) {
        // FastAPI sends 422 `detail` as an array of {loc, msg}. Without
        // ApiError.detail this rendered as "[object Object]".
        setFieldErrors(mutationError.fieldErrors() ?? {});
        setError(mutationError.message);
      } else {
        setError(String(mutationError));
      }
    },
  });

  const incumbentId =
    (live.data?.entries ?? []).find(
      (entry) =>
        entry.type === form.type &&
        entry.id !== Number(entryId) &&
        (entry.slug.toLowerCase() === (form.slug || "").toLowerCase() ||
          entry.title.toLowerCase() === form.title.toLowerCase()),
    )?.id ?? null;

  function submit(publish: boolean) {
    setError(null);
    setFieldErrors({});
    const input = buildInput();
    if (input !== null) save.mutate({ input, publish });
  }

  if (editing && existing.isPending) {
    return <div className={viewFrameStyles.canvasMessage}>Loading…</div>;
  }
  if (editing && existing.isError) {
    return (
      <div className={viewFrameStyles.canvasMessage}>
        Failed to load entry: {String(existing.error)}
      </div>
    );
  }

  return (
    <div className={styles.editor}>
      <div className={styles.header}>
        <h1 className={styles.title}>{editing ? "Edit entry" : "New entry"}</h1>
        <Button variant="ghost" onClick={() => navigate(-1)}>
          Cancel
        </Button>
      </div>

      <form
        className={styles.body}
        onSubmit={(event) => {
          event.preventDefault();
          submit(false);
        }}
      >
        <label className={styles.field}>
          <span className={styles.label}>type</span>
          {/* Disabled while editing: changing the type changes which payload
              schema applies, which would silently invalidate the payload. */}
          <Select
            value={form.type}
            disabled={editing}
            onValueChange={(value) => set("type", value)}
          >
            <SelectTrigger aria-label="type">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(types.data?.types ?? []).map((kbType) => (
                <SelectItem key={kbType.name} value={kbType.name}>
                  {kbType.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>

        <label className={styles.field}>
          <span className={styles.label}>title</span>
          <Input
            required
            value={form.title}
            onChange={(event) => set("title", event.target.value)}
          />
          {fieldErrors.title && <span className={styles.error}>{fieldErrors.title}</span>}
        </label>

        <label className={styles.field}>
          <span className={styles.label}>slug</span>
          <Input
            placeholder="derived from the title when blank"
            value={form.slug}
            onChange={(event) => set("slug", event.target.value)}
          />
          {fieldErrors.slug && <span className={styles.error}>{fieldErrors.slug}</span>}
        </label>

        <label className={styles.field}>
          <span className={styles.label}>aliases</span>
          <Input
            placeholder="comma separated"
            value={form.aliases}
            onChange={(event) => set("aliases", event.target.value)}
          />
        </label>

        <label className={styles.field}>
          <span className={styles.label}>body</span>
          <Textarea
            required
            value={form.body}
            onChange={(event) => set("body", event.target.value)}
          />
          {fieldErrors.body && <span className={styles.error}>{fieldErrors.body}</span>}
        </label>

        <label className={styles.field}>
          <span className={styles.label}>
            payload (JSON)
            {/* v1 is a raw textarea and that is ugly. The clean version drives
                inputs off /kb/types' payload_schema; it can be added later
                against the same endpoint with no API change. */}
          </span>
          <Textarea
            variant="mono"
            value={form.payload}
            onChange={(event) => set("payload", event.target.value)}
          />
          {payloadError && <span className={styles.error}>{payloadError}</span>}
          {fieldErrors.payload && (
            <span className={styles.error}>{fieldErrors.payload}</span>
          )}
          {types.data && (
            <span className={styles.hint}>
              {Object.entries(
                types.data.types.find((t) => t.name === form.type)?.payload_fields ?? {},
              )
                .map(([name, shape]) => `${name}: ${shape}`)
                .join(" · ")}
            </span>
          )}
        </label>

        <label className={styles.field}>
          <span className={styles.label}>scope</span>
          <Select
            value={form.repository}
            onValueChange={(value) => set("repository", value)}
          >
            <SelectTrigger aria-label="scope">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={GLOBAL}>global (every repository)</SelectItem>
              {repoList().map((name) => (
                <SelectItem key={name} value={name}>
                  {name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>

        {error && <p className={styles.error}>{error}</p>}

        <div className={styles.actions}>
          <Button type="submit" disabled={save.isPending}>
            {editing ? "Save" : "Save as draft"}
          </Button>
          <Button
            variant="primary"
            disabled={save.isPending}
            onClick={() => submit(true)}
          >
            {incumbentId === null ? "Save & publish" : "Save & publish, replacing"}
          </Button>
        </div>
      </form>
    </div>
  );
}
