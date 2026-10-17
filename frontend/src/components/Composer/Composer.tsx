import { useState, type FormEvent, type KeyboardEvent } from "react";
import { ArrowUpIcon, PaperclipIcon } from "../icons/Icons";
import "./Composer.css";

interface ComposerProps {
  /** Return false to keep the text in the box (e.g. the message could not be sent yet). */
  onSend: (text: string) => boolean | void;
  onAttach: () => void;
}

export function Composer({ onSend, onAttach }: ComposerProps) {
  const [text, setText] = useState("");

  // Shell: the button is always clickable; sending is a stub until the chat backend exists.
  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    if (onSend(text.trim()) === false) return;
    setText("");
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) submit(e);
  };

  return (
    <form className="composer" aria-label="Ask SCRAP" onSubmit={submit}>
      <button className="attach" type="button" aria-label="Attach dataset" onClick={onAttach}>
        <PaperclipIcon />
      </button>
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
