;;; vox-mode.el --- Major mode for HAT .vox layer files -*- lexical-binding: t; -*-

;; Install (from a checkout of this repo):
;;   (load "/ABSOLUTE/PATH/TO/utils/vox2stl/emacs/vox-mode.el")
;; Or add that emacs/ directory to `load-path` and (require 'vox-mode).
;; Files matching \\.vox\\' open in vox-mode via auto-mode-alist.
;;
;; voxtool.py is resolved next to this file: ../voxtool.py (the vox2stl/ tree).
;; Transform commands save the buffer, run the tool on `buffer-file-name`, then
;; revert when the tool rewrites the file (correct / mirror).

;;; Commentary:
;; Thin Emacs major mode for hand-editing HAT .vox files. Font-lock and
;; navigation live here; legality-preserving transforms shell out to
;; vox2stl/voxtool.py via `call-process`.

;;; Code:

(defgroup vox-mode nil
  "Editing support for HAT .vox layer files."
  :group 'languages)

(defcustom vox-mode-python-command "python3"
  "Python interpreter used to run `voxtool.py'."
  :type 'string
  :group 'vox-mode)

(defconst vox-mode--directory
  (file-name-directory (or load-file-name buffer-file-name))
  "Directory containing this `vox-mode.el' file.")

(defvar vox-mode-syntax-table
  (let ((table (make-syntax-table)))
    ;; Treat # as comment start to end of line (line comments).
    (modify-syntax-entry ?# "<" table)
    (modify-syntax-entry ?\n ">" table)
    table)
  "Syntax table for `vox-mode'.")

(defconst vox-mode-font-lock-keywords
  `(
    ;; Layer headers: layer NAME (ARGS)
    ("^\\s-*\\(layer\\)\\s-+\\([A-Za-z0-9_-]+\\)\\s-*("
     (1 font-lock-keyword-face)
     (2 font-lock-function-name-face))
    ;; Alias / net alias declarations
    ("^\\s-*\\(alias\\|net\\s-+alias\\)\\b" 1 font-lock-builtin-face)
    ;; Through-pads
    ("[*O]" 0 font-lock-warning-face)
    ;; Trace / connection glyphs (ASCII + common box-drawing)
    ("[-|+/\\\\<>^]" 0 font-lock-type-face)
    ("[\u2500\u2502\u250c\u2510\u2514\u2518\u251c\u2524\u252c\u2534\u253c]"
     0 font-lock-type-face)
    ;; Lowercase letter labels in the design window
    ("\\b[a-z]\\b" 0 font-lock-constant-face)
    ;; Base fill
    ("[X]" 0 font-lock-comment-delimiter-face)
    ;; Empty trace cells
    ("[.]", 0 font-lock-comment-face))
  "Font-lock keywords for `vox-mode'.")

(defun vox-mode--voxtool ()
  "Absolute path to sibling `voxtool.py' under vox2stl/."
  (expand-file-name "../voxtool.py" vox-mode--directory))
(defun vox-mode--require-file-buffer ()
  "Return `buffer-file-name', or signal a user error if unset."
  (unless buffer-file-name
    (user-error "vox-mode: buffer is not visiting a file"))
  buffer-file-name)

(defun vox-mode--run-voxtool (subcommand &optional revert-after)
  "Save buffer, run voxtool.py SUBCOMMAND on it; REVERT-AFTER reloads if rewritten."
  (let* ((path (vox-mode--require-file-buffer))
         (tool (vox-mode--voxtool))
         (buf (get-buffer-create "*voxtool*")))
    (unless (file-executable-p tool)
      ;; Still runnable via python even when the +x bit is missing.
      (unless (file-readable-p tool)
        (user-error "vox-mode: cannot find voxtool.py at %s" tool)))
    (when (buffer-modified-p)
      (save-buffer))
    (with-current-buffer buf
      (erase-buffer))
    (let ((status (call-process vox-mode-python-command nil buf t
                                tool subcommand path)))
      (when (and revert-after (zerop status))
        (revert-buffer t t t))
      (when (not (zerop status))
        (display-buffer buf)
        (user-error "vox-mode: voxtool.py %s failed (exit %s); see *voxtool*"
                    subcommand status))
      (message "vox-mode: voxtool.py %s ok" subcommand)
      status)))

;;;###autoload
(defun vox-mode-check ()
  "Validate the current .vox file with `voxtool.py check'."
  (interactive)
  (vox-mode--run-voxtool "check" nil))

;;;###autoload
(defun vox-mode-correct ()
  "Normalize shorthand in the current .vox file with `voxtool.py correct'."
  (interactive)
  (vox-mode--run-voxtool "correct" t))

;;;###autoload
(defun vox-mode-mirror ()
  "Mirror the current .vox file in place with `voxtool.py mirror'."
  (interactive)
  (vox-mode--run-voxtool "mirror" t))

;;;###autoload
(defun vox-mode-reheader ()
  "Rewrite layer height_rows to match data rows via `voxtool.py reheader'."
  (interactive)
  (vox-mode--run-voxtool "reheader" t))

;;;###autoload
(defun vox-mode-sync-pads-from-trace ()
  "Upsert * / O from trace into base via `voxtool.py sync-pads'."
  (interactive)
  (vox-mode--run-voxtool-args '("sync-pads" "--from=trace" "--to=base") t))

;;;###autoload
(defun vox-mode-sync-pads-from-base ()
  "Upsert * / O from base into trace via `voxtool.py sync-pads'."
  (interactive)
  (vox-mode--run-voxtool-args '("sync-pads" "--from=base" "--to=trace") t))

;;;###autoload
(defun vox-mode-indent ()
  "Increase horizontal_offset by 1 via `voxtool.py indent --delta 1'."
  (interactive)
  (vox-mode--run-voxtool-args '("indent" "--delta" "1") t))

;;;###autoload
(defun vox-mode-outdent ()
  "Decrease horizontal_offset by 1 via `voxtool.py indent --delta -1'."
  (interactive)
  (vox-mode--run-voxtool-args '("indent" "--delta" "-1") t))

(defun vox-mode--run-voxtool-args (args &optional revert-after)
  "Save buffer, run voxtool.py with ARGS; REVERT-AFTER reloads if rewritten."
  (let* ((path (vox-mode--require-file-buffer))
         (tool (vox-mode--voxtool))
         (buf (get-buffer-create "*voxtool*"))
         (subcommand (car args)))
    (unless (file-readable-p tool)
      (user-error "vox-mode: cannot find voxtool.py at %s" tool))
    (when (buffer-modified-p)
      (save-buffer))
    (with-current-buffer buf
      (erase-buffer))
    (let ((status (apply #'call-process vox-mode-python-command nil buf t
                         tool (append args (list path)))))
      (when (and revert-after (zerop status))
        (revert-buffer t t t))
      (when (not (zerop status))
        (display-buffer buf)
        (user-error "vox-mode: voxtool.py %s failed (exit %s); see *voxtool*"
                    subcommand status))
      (message "vox-mode: voxtool.py %s ok" subcommand)
      status)))

(defvar vox-mode-map
  (let ((map (make-sparse-keymap)))
    (define-key map (kbd "C-c C-c") #'vox-mode-check)
    (define-key map (kbd "C-c C-o") #'vox-mode-correct)
    (define-key map (kbd "C-c C-m") #'vox-mode-mirror)
    (define-key map (kbd "C-c C-h") #'vox-mode-reheader)
    (define-key map (kbd "C-c C-t") #'vox-mode-sync-pads-from-trace)
    (define-key map (kbd "C-c C-b") #'vox-mode-sync-pads-from-base)
    (define-key map (kbd "C-c C-i") #'vox-mode-indent)
    (define-key map (kbd "C-c C-u") #'vox-mode-outdent)
    map)
  "Keymap for `vox-mode'.")

;;;###autoload
(define-derived-mode vox-mode prog-mode "Vox"
  "Major mode for editing HAT .vox layer design files.

Commands:
\\<vox-mode-map>
\\[vox-mode-check]               Run `voxtool.py check' on the visited file.
\\[vox-mode-correct]             Run `voxtool.py correct' (save, rewrite, revert).
\\[vox-mode-mirror]              Run `voxtool.py mirror' (save, rewrite, revert).
\\[vox-mode-reheader]            Run `voxtool.py reheader' (save, rewrite, revert).
\\[vox-mode-sync-pads-from-trace] Upsert pads trace -> base.
\\[vox-mode-sync-pads-from-base]  Upsert pads base -> trace.
\\[vox-mode-indent]              Indent design window (+1 offset).
\\[vox-mode-outdent]             Outdent design window (-1 offset)."
  :syntax-table vox-mode-syntax-table
  (setq-local comment-start "# ")
  (setq-local comment-start-skip "#+\\s-*")
  (setq-local font-lock-defaults '(vox-mode-font-lock-keywords)))

;;;###autoload
(add-to-list 'auto-mode-alist '("\\.vox\\'" . vox-mode))

(provide 'vox-mode)

;;; vox-mode.el ends here
