import { FormEvent, useEffect, useState } from "react";

import {
  bulkAddRepositories,
  bulkRemoveRepositories,
  discoverGitHubRepositories,
  type GitHubRepositoryDiscovery,
  type RepositoryCreatePayload,
} from "../../services/api";
import { SourceControlProviderEnum } from "../../types/enums";
import styles from "./GitHubDiscoveryModal.module.css";

interface GitHubDiscoveryModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

export default function GitHubDiscoveryModal({ isOpen, onClose, onSuccess }: GitHubDiscoveryModalProps) {
  const [organization, setOrganization] = useState("");
  const [discovering, setDiscovering] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [repositories, setRepositories] = useState<GitHubRepositoryDiscovery[]>([]);
  const [selectedRepos, setSelectedRepos] = useState<Set<number>>(new Set());
  const [discoveryComplete, setDiscoveryComplete] = useState(false);

  // Stats
  const [totalRepositories, setTotalRepositories] = useState(0);
  const [trackedCount, setTrackedCount] = useState(0);
  const [untrackedCount, setUntrackedCount] = useState(0);

  useEffect(() => {
    if (!isOpen) {
      setOrganization("");
      setRepositories([]);
      setSelectedRepos(new Set());
      setDiscoveryComplete(false);
      setError(null);
    }
  }, [isOpen]);

  const handleDiscover = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!organization.trim()) return;

    setDiscovering(true);
    setError(null);

    try {
      const response = await discoverGitHubRepositories(organization.trim());
      setRepositories(response.repositories);
      setTotalRepositories(response.total_repositories);
      setTrackedCount(response.tracked_count);
      setUntrackedCount(response.untracked_count);
      setDiscoveryComplete(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to discover GitHub repositories");
    } finally {
      setDiscovering(false);
    }
  };

  const handleSelectAll = () => {
    const untracked = repositories.filter((r) => !r.is_tracked);
    setSelectedRepos(new Set(untracked.map((r) => r.github_repo_id)));
  };

  const handleDeselectAll = () => {
    setSelectedRepos(new Set());
  };

  const handleToggleRepo = (githubId: number) => {
    const newSelected = new Set(selectedRepos);
    if (newSelected.has(githubId)) {
      newSelected.delete(githubId);
    } else {
      newSelected.add(githubId);
    }
    setSelectedRepos(newSelected);
  };

  const handleAddSelected = async () => {
    if (selectedRepos.size === 0) return;

    setProcessing(true);
    setError(null);

    try {
      const repositoriesToAdd: RepositoryCreatePayload[] = repositories
        .filter((r) => selectedRepos.has(r.github_repo_id) && !r.is_tracked)
        .map((r) => ({
          provider: SourceControlProviderEnum.github,
          github_repo_id: r.github_repo_id,
          github_owner: r.github_owner,
          name: r.name,
          path_with_namespace: r.path_with_namespace,
          url: r.url,
          clone_url: r.clone_url,
          default_branch: r.default_branch,
        }));

      const response = await bulkAddRepositories(repositoriesToAdd);

      if (response.failed_count > 0) {
        setError(`Added ${response.added_count}, failed ${response.failed_count}: ${response.errors.join(", ")}`);
      }

      // Refresh discovery to update tracking status
      const refreshed = await discoverGitHubRepositories(organization.trim());
      setRepositories(refreshed.repositories);
      setTrackedCount(refreshed.tracked_count);
      setUntrackedCount(refreshed.untracked_count);
      setSelectedRepos(new Set());

      if (response.added_count > 0) {
        onSuccess();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add repositories");
    } finally {
      setProcessing(false);
    }
  };

  const handleRemoveSelected = async () => {
    if (selectedRepos.size === 0) return;

    const confirmed = window.confirm(
      `Are you sure you want to remove ${selectedRepos.size} repositories? This will delete all associated data.`
    );
    if (!confirmed) return;

    setProcessing(true);
    setError(null);

    try {
      const repositoryIdsToRemove = repositories
        .filter((r) => selectedRepos.has(r.github_repo_id) && r.is_tracked && r.tracked_repository_id)
        .map((r) => r.tracked_repository_id!);

      const response = await bulkRemoveRepositories(repositoryIdsToRemove);

      if (response.failed_count > 0) {
        setError(`Removed ${response.removed_count}, failed ${response.failed_count}: ${response.errors.join(", ")}`);
      }

      // Refresh discovery to update tracking status
      const refreshed = await discoverGitHubRepositories(organization.trim());
      setRepositories(refreshed.repositories);
      setTrackedCount(refreshed.tracked_count);
      setUntrackedCount(refreshed.untracked_count);
      setSelectedRepos(new Set());

      if (response.removed_count > 0) {
        onSuccess();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to remove repositories");
    } finally {
      setProcessing(false);
    }
  };

  if (!isOpen) return null;

  const selectedUntrackedCount = Array.from(selectedRepos).filter((id) => {
    const repo = repositories.find((r) => r.github_repo_id === id);
    return repo && !repo.is_tracked;
  }).length;

  const selectedTrackedCount = Array.from(selectedRepos).filter((id) => {
    const repo = repositories.find((r) => r.github_repo_id === id);
    return repo && repo.is_tracked;
  }).length;

  return (
    <div className={styles.modal_overlay} onClick={onClose}>
      <div className={styles.modal_content} onClick={(e) => e.stopPropagation()}>
        <div className={styles.modal_header}>
          <h2 className={styles.modal_title}>Discover GitHub Repositories</h2>
          <button className={styles.close_button} onClick={onClose} type="button">
            ✕
          </button>
        </div>

        {!discoveryComplete ? (
          <form onSubmit={handleDiscover} className={styles.discovery_form}>
            <div className={styles.form_row}>
              <label htmlFor="organization" className={styles.form_label}>
                GitHub Organization or Username
              </label>
              <input
                id="organization"
                type="text"
                className={styles.form_input}
                value={organization}
                onChange={(e) => setOrganization(e.target.value)}
                placeholder="e.g., anthropics or octocat"
                disabled={discovering}
                required
              />
              <p className={styles.field_hint}>Enter the GitHub organization or username to discover all repositories</p>
            </div>

            {error && (
              <div className={styles.error_message}>
                <strong>Error:</strong> {error}
              </div>
            )}

            <div className={styles.form_actions}>
              <button type="button" className={styles.secondary_button} onClick={onClose} disabled={discovering}>
                Cancel
              </button>
              <button type="submit" className={styles.primary_button} disabled={discovering || !organization.trim()}>
                {discovering ? "Discovering..." : "Discover Repositories"}
              </button>
            </div>
          </form>
        ) : (
          <div className={styles.results_container}>
            <div className={styles.stats_bar}>
              <div className={styles.stat_item}>
                <span className={styles.stat_label}>Total:</span>
                <span className={styles.stat_value}>{totalRepositories}</span>
              </div>
              <div className={styles.stat_item}>
                <span className={styles.stat_label}>Tracked:</span>
                <span className={styles.stat_value_tracked}>{trackedCount}</span>
              </div>
              <div className={styles.stat_item}>
                <span className={styles.stat_label}>Untracked:</span>
                <span className={styles.stat_value_untracked}>{untrackedCount}</span>
              </div>
            </div>

            <div className={styles.selection_bar}>
              <div className={styles.selection_info}>
                {selectedRepos.size > 0 ? (
                  <span>
                    {selectedRepos.size} selected ({selectedUntrackedCount} untracked, {selectedTrackedCount}{" "}
                    tracked)
                  </span>
                ) : (
                  <span>No repositories selected</span>
                )}
              </div>
              <div className={styles.selection_actions}>
                <button
                  type="button"
                  className={styles.text_button}
                  onClick={handleSelectAll}
                  disabled={untrackedCount === 0}
                >
                  Select All Untracked
                </button>
                <button
                  type="button"
                  className={styles.text_button}
                  onClick={handleDeselectAll}
                  disabled={selectedRepos.size === 0}
                >
                  Deselect All
                </button>
              </div>
            </div>

            {error && (
              <div className={styles.error_message}>
                <strong>Error:</strong> {error}
              </div>
            )}

            <div className={styles.projects_list}>
              {repositories.map((repo) => (
                <div
                  key={repo.github_repo_id}
                  className={`${styles.project_item} ${repo.is_tracked ? styles.project_tracked : ""}`}
                >
                  <input
                    type="checkbox"
                    className={styles.project_checkbox}
                    checked={selectedRepos.has(repo.github_repo_id)}
                    onChange={() => handleToggleRepo(repo.github_repo_id)}
                    disabled={processing}
                  />
                  <div className={styles.project_info}>
                    <div className={styles.project_header}>
                      <span className={styles.project_name}>{repo.name}</span>
                      {repo.is_tracked && <span className={styles.tracked_badge}>Tracked</span>}
                      {repo.is_fork && <span className={styles.fork_badge}>Fork</span>}
                    </div>
                    <div className={styles.project_path}>{repo.path_with_namespace}</div>
                    {repo.description && <div className={styles.project_description}>{repo.description}</div>}
                    <div className={styles.project_meta}>
                      <span>Branch: {repo.default_branch}</span>
                      {repo.visibility && <span>• {repo.visibility}</span>}
                    </div>
                  </div>
                </div>
              ))}
            </div>

            <div className={styles.modal_footer}>
              <button type="button" className={styles.secondary_button} onClick={onClose} disabled={processing}>
                Close
              </button>
              <button
                type="button"
                className={styles.secondary_button}
                onClick={() => {
                  setDiscoveryComplete(false);
                  setRepositories([]);
                  setSelectedRepos(new Set());
                }}
                disabled={processing}
              >
                Back to Search
              </button>
              {selectedTrackedCount > 0 && (
                <button
                  type="button"
                  className={styles.danger_button}
                  onClick={handleRemoveSelected}
                  disabled={processing || selectedTrackedCount === 0}
                >
                  {processing ? "Removing..." : `Remove ${selectedTrackedCount} Tracked`}
                </button>
              )}
              {selectedUntrackedCount > 0 && (
                <button
                  type="button"
                  className={styles.primary_button}
                  onClick={handleAddSelected}
                  disabled={processing || selectedUntrackedCount === 0}
                >
                  {processing ? "Adding..." : `Add ${selectedUntrackedCount} Repositories`}
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
