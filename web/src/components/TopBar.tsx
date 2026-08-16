import { useNavigate } from "react-router-dom";

import { repoList, useAppStore } from "../store";

export default function TopBar() {
  const repo = useAppStore((state) => state.repo);
  const setRepo = useAppStore((state) => state.setRepo);
  const navigate = useNavigate();
  const repos = repoList();

  return (
    <header className="top-bar">
      <button
        type="button"
        className="app-title"
        onClick={() => navigate("/")}
      >
        CodeGraph
      </button>
      <label className="repo-select">
        repo
        <select
          value={repo ?? ""}
          onChange={(event) => {
            setRepo(event.target.value || null);
            navigate("/");
          }}
        >
          {repos.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      </label>
    </header>
  );
}
