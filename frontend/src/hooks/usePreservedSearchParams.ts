import { useSearchParams, type NavigateOptions, type URLSearchParamsInit } from 'react-router-dom'

/** URL filter changes should preserve the current workspace position. */
export function usePreservedSearchParams(defaultInit?: URLSearchParamsInit) {
  const [searchParams, setSearchParams] = useSearchParams(defaultInit)

  const setPreservedSearchParams = (
    nextInit?: URLSearchParamsInit | ((previous: URLSearchParams) => URLSearchParamsInit),
    options?: NavigateOptions,
  ) => setSearchParams(nextInit, { ...options, preventScrollReset: true })

  return [searchParams, setPreservedSearchParams] as const
}
