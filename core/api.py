        # GitHub repos shortcut
        if any(k in lower for k in ["list repos", "my repos", "github repos", "list my repo"]):
            result = await run_tool("list_repos")
            if isinstance(result, dict) and "repos" in result:
                lines = ["**📁 Your GitHub Repos**\n"]
                for r in result["repos"]:
                    icon = "🔒" if r["private"] else "📂"
                    desc = f" — {r['description']}" if r.get("description") else ""
                    lines.append(f"{icon} **{r['name']}**{desc}")
                return {"reply": "\n".join(lines)}

        # Default — chat
        reply = _brain.chat(req.user_id, req.message)
        return {"reply": reply}
