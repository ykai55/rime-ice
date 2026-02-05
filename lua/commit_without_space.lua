local M = {}

function M.func(key, env)
  local ctx = env.engine.context
  if not ctx:is_composing() then return 2 end

  local repr = key:repr()

  -- 提交解析后的拼音串去空格 nihao
  if repr == "F13" then
    local s = ctx:get_script_text()
    if s and s ~= "" then
      env.engine:commit_text((s:gsub("%s+", "")))
      ctx:clear()
      return 1
    end
    return 2
  end

  return 2
end

return M

