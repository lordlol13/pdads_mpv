import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { newsService } from '../api/services';
import { InteractionCreateRequest } from '../types';

export const useNewsFeed = () => {
  return useQuery({
    queryKey: ['news-feed'],
    queryFn: () => newsService.getFeed(50),
    initialData: [],
  });
};

export const useReactToNews = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: InteractionCreateRequest) => newsService.react(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['news-feed'] });
    },
  });
};
