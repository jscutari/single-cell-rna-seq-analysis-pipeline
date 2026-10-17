import { useEffect, useRef, type ReactNode } from "react";
import logo from "../../assets/scrap-logo.png";
import type { ChatMessage } from "../../types/schemas";
import "./ChatView.css";

interface ChatViewProps {
  messages: ChatMessage[];
  awaitingReply: boolean;
}

/** Page view once a project has a conversation: replaces the welcome sheet and doodles. */
export function ChatView({ messages, awaitingReply }: ChatViewProps) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [messages.length, awaitingReply]);

  return (
    <div className="chat-scroll">
      <div className="chat-log" role="log" aria-live="polite" aria-label="Conversation">
        {messages.map((message) =>
          message.role === "user" ? (
            <div key={message.id} className="chat-row chat-row--user">
              <p className="bubble bubble--user">{message.content}</p>
            </div>
          ) : (
            <AssistantRow key={message.id}>
              <p className="bubble bubble--assistant">{message.content}</p>
            </AssistantRow>
          ),
        )}
        {awaitingReply && (
          <AssistantRow>
            <p className="bubble bubble--assistant bubble--typing" aria-label="SCRAP is typing">
              <span />
              <span />
              <span />
            </p>
          </AssistantRow>
        )}
        <div ref={endRef} />
      </div>
    </div>
  );
}

function AssistantRow({ children }: { children: ReactNode }) {
  return (
    <div className="chat-row chat-row--assistant">
      <div className="chat-avatar" aria-hidden="true">
        <img src={logo} alt="" />
      </div>
      {children}
    </div>
  );
}
