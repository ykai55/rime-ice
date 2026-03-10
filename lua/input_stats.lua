local kNoop = 2

local function csv_escape(value)
  if value == nil then
    return ""
  end

  local text = tostring(value)
  text = text:gsub('"', '""')
  if text:find('[,\n\r"]') then
    return '"' .. text .. '"'
  end
  return text
end

local function char_count(text)
  if text == nil or text == "" then
    return 0
  end

  if utf8 and utf8.len then
    local ok, length = pcall(utf8.len, text)
    if ok and length ~= nil then
      return length
    end
  end

  return #text
end

local function user_data_dir()
  if rime_api and rime_api.get_user_data_dir then
    return rime_api.get_user_data_dir()
  end
  return "."
end

local function resolve_output_path(configured_path)
  if configured_path and configured_path ~= "" then
    if configured_path:match("^/") or configured_path:match("^[A-Za-z]:[\\/]") then
      return configured_path
    end
    return user_data_dir() .. "/" .. configured_path
  end

  return user_data_dir() .. "/input_stats/events.csv"
end

local function shell_escape(path)
  return '"' .. tostring(path):gsub('"', '\\"') .. '"'
end

local function ensure_parent_dir(path)
  local dir = path:match("^(.*)[/\\][^/\\]+$")
  if not dir or dir == "" then
    return
  end

  local is_windows = package and package.config and package.config:sub(1, 1) == "\\"
  if is_windows then
    os.execute("mkdir " .. shell_escape(dir) .. " >nul 2>nul")
  else
    os.execute("mkdir -p " .. shell_escape(dir) .. " >/dev/null 2>&1")
  end
end

local function ensure_csv_header(path)
  local existing = io.open(path, "r")
  if existing then
    local first_line = existing:read("*l")
    existing:close()
    if first_line and first_line:match("^epoch,") then
      return
    end
  end

  local output = io.open(path, "w")
  if output then
    output:write("epoch,iso,chars,schema,text\n")
    output:close()
  end
end

local function append_event(env, commit_text)
  local now = os.time()
  local iso = os.date("%Y-%m-%dT%H:%M:%S%z", now)
  local schema_id = ""

  if env.engine and env.engine.schema and env.engine.schema.schema_id then
    schema_id = env.engine.schema.schema_id
  end

  local chars = char_count(commit_text)
  local text = ""
  if env.save_text then
    text = commit_text
  end

  local row = table.concat({
    csv_escape(now),
    csv_escape(iso),
    csv_escape(chars),
    csv_escape(schema_id),
    csv_escape(text),
  }, ",") .. "\n"

  local output = io.open(env.file_path, "a")
  if output then
    output:write(row)
    output:close()
  end
end

local M = {}

function M.init(env)
  local config = env.engine.schema.config

  local configured_path = config:get_string("input_stats/file_path")
  env.file_path = resolve_output_path(configured_path)

  local save_text = config:get_bool("input_stats/save_text")
  if save_text == nil then
    save_text = false
  end
  env.save_text = save_text

  ensure_parent_dir(env.file_path)
  ensure_csv_header(env.file_path)

  env.commit_connection = env.engine.context.commit_notifier:connect(function(context)
    local commit_text = context:get_commit_text()
    if commit_text and commit_text ~= "" then
      append_event(env, commit_text)
    end
  end)
end

function M.fini(env)
  if env.commit_connection then
    env.commit_connection:disconnect()
    env.commit_connection = nil
  end
end

function M.func(_, _)
  return kNoop
end

return M
