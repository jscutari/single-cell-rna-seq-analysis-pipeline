import { useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { ArrowUpIcon, CloseIcon, PaperclipIcon } from "../icons/Icons";
import "./Composer.css";

export interface Attachment {
  id: string;
  name: string;
}

interface ComposerProps {
  /** Return false to keep the text in the box (e.g. the message could not be sent yet). */
  onSend: (text: string) => boolean | void;
  /** Files picked with the paperclip. Without it, the paperclip calls onAttach. */
  onAttachFiles?: (files: File[]) => void;
  onAttach?: () => void;
  /** Files waiting to go out with the next message. */
  attachments?: Attachment[];
  onRemoveAttachment?: (id: string) => void;
}

export function Composer({ onSend, onAttachFiles, onAttach, attachments = [], onRemoveAttachment }: ComposerProps) {
  const [text, setText] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    if (onSend(text.trim()) === false) return;
    setText("");
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) submit(e);
  };

  return (
    <form className={attachments.length ? "composer composer--with-files" : "composer"} aria-label="Ask SCRAP" onSubmit={submit}>
      {attachments.length > 0 && (
        <ul className="composer-files" aria-label="Attached files">
          {attachments.map((a) => (
            <li key={a.id} className="composer-file">
              <span className="composer-file-name">{a.name}</span>
              {onRemoveAttachment && (
                <button type="button" aria-label={`Remove ${a.name}`} onClick={() => onRemoveAttachment(a.id)}>
                  <CloseIcon />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      <button
        className="attach"
        type="button"
        aria-label="Attach files"
        onClick={() => (onAttachFiles ? fileInput.current?.click() : onAttach?.())}
      >
        <PaperclipIcon />
      </button>
      {onAttachFiles && (
        <input
          ref={fileInput}
          className="sr-only"
          type="file"
          multiple
          aria-label="Choose files to attach"
          tabIndex={-1}
          onChange={(e) => {
            const picked = Array.from(e.target.files ?? []);
            if (picked.length) onAttachFiles(picked);
            e.target.value = "";
          }}
        />
      )}
      <label className="sr-only" htmlFor="prompt">
        Ask SCRAP anything about your data
      </label>
      <textarea
        id="prompt"
        className="chat-input"
        rows={1}
        placeholder="Ask SCRAP anything about your data..."
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
      />
      <button className="send" type="submit" aria-label="Send message">
        <ArrowUpIcon />
      </button>
    </form>
  );
}
