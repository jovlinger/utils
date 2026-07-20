;;; vox-mode.el --- Major mode for HAT .vox layer files -*- lexical-binding: t; -*-

;; Install (from a checkout of this repo):
;;   (load "/ABSOLUTE/PATH/TO/utils/vox2stl/emacs/vox-mode.el")
;; Or add the emacs/ directory to load-path and (require 'vox-mode).
;; Files matching \\.vox\\' open in vox-mode via auto-mode-alist.

;;; Commentary:
;; Thin Emacs major mode for hand-editing HAT .vox files. Font-lock and
;; navigation live here; legality-preserving transforms should shell out to
;; vox2stl/voxtool.py (see sibling wrappers added in later work items).

;;; Code:

(defgroup vox-mode nil
  "Editing support for HAT .vox layer files."
  :group 'languages)

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

;;;###autoload
(define-derived-mode vox-mode prog-mode "Vox"
  "Major mode for editing HAT .vox layer design files."
  :syntax-table vox-mode-syntax-table
  (setq-local comment-start "# ")
  (setq-local comment-start-skip "#+\\s-*")
  (setq-local font-lock-defaults '(vox-mode-font-lock-keywords)))

;;;###autoload
(add-to-list 'auto-mode-alist '("\\.vox\\'" . vox-mode))

(provide 'vox-mode)

;;; vox-mode.el ends here
