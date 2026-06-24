import React, { createContext, useContext, useCallback, useEffect, useRef } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { selectIsAuthenticated } from '../redux/features/auth/authSlice';
import { 
  useGetRecentNotificationsQuery,
  useGetUnreadCountQuery,
  notificationsApi
} from '../redux/features/api/notifications/notificationsApi';
import { useNotificationSound } from '../../hooks/useNotificationSound';

interface NotificationContextType {
  notifications: any[];
  unreadCount: number;
  isLoading: boolean;
  refreshNotifications: () => void;
  clearCache: () => void;
  testNotificationSound: (type?: 'default' | 'success' | 'warning' | 'error') => void;
  isSoundEnabled: boolean;
}

const NotificationContext = createContext<NotificationContextType | undefined>(undefined);

export const NotificationProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const dispatch = useDispatch();
  const isAuthenticated = useSelector(selectIsAuthenticated);
  const { playNotificationSound, isSoundEnabled } = useNotificationSound();
  const previousNotificationCountRef = useRef<number>(0);
  const isInitialLoadRef = useRef(true);
  
  const { 
    data: notifications = [], 
    isLoading,
    refetch: refetchNotifications 
  } = useGetRecentNotificationsQuery(undefined, {
    skip: !isAuthenticated
  });
  
  const { 
    data: unreadCountData,
    refetch: refetchUnreadCount 
  } = useGetUnreadCountQuery(undefined, {
    skip: !isAuthenticated
  });

  const refreshNotifications = useCallback(() => {
    if (isAuthenticated) {
      refetchNotifications();
      refetchUnreadCount();
    }
  }, [isAuthenticated, refetchNotifications, refetchUnreadCount]);

  const clearCache = useCallback(() => {
    dispatch(notificationsApi.util.invalidateTags(['Notifications']));
  }, [dispatch]);

  // Detect new notifications and play sound
  useEffect(() => {
    if (isLoading || !notifications) return;

    const currentUnreadCount = unreadCountData?.count || 0;
    const previousUnreadCount = previousNotificationCountRef.current;

    // Skip sound on initial load
    if (isInitialLoadRef.current) {
      previousNotificationCountRef.current = currentUnreadCount;
      isInitialLoadRef.current = false;
      return;
    }

    // Play sound if there are new unread notifications
    if (currentUnreadCount > previousUnreadCount && isSoundEnabled) {
      // Determine notification type for appropriate sound
      const latestNotification = notifications[0];
      let soundType: 'default' | 'success' | 'warning' | 'error' = 'default';

      if (latestNotification) {
        switch (latestNotification.notification_type) {
          case 'ML_PROCESSING_FAILED':
          case 'SYSTEM_ALERT':
            soundType = 'error';
            break;
          case 'CREDIT_SCORE_GENERATED':
          case 'ML_PROCESSING_COMPLETED':
            soundType = 'success';
            break;
          case 'STATUS_CHANGE':
          case 'DECISION_MADE':
            soundType = 'warning';
            break;
          default:
            soundType = 'default';
        }
      }

      // Play sound with slight delay to ensure UI is updated
      setTimeout(() => {
        playNotificationSound(soundType);
      }, 100);
    }

    previousNotificationCountRef.current = currentUnreadCount;
  }, [notifications, unreadCountData, isLoading, isSoundEnabled, playNotificationSound]);

  // Auto-refresh notifications every 30 seconds when tab is active
  useEffect(() => {
    let interval: NodeJS.Timeout;
    
    const handleVisibilityChange = () => {
      if (!document.hidden && isAuthenticated) {
        refreshNotifications();
      }
    };

    if (typeof window !== 'undefined' && isAuthenticated) {
      document.addEventListener('visibilitychange', handleVisibilityChange);
      
      interval = setInterval(() => {
        if (!document.hidden && isAuthenticated) {
          refreshNotifications();
        }
      }, 30000); // 30 seconds
    }

    return () => {
      if (typeof window !== 'undefined') {
        document.removeEventListener('visibilitychange', handleVisibilityChange);
      }
      if (interval) {
        clearInterval(interval);
      }
    };
  }, [refreshNotifications, isAuthenticated]);

  const testNotificationSound = useCallback((type: 'default' | 'success' | 'warning' | 'error' = 'default') => {
    playNotificationSound(type);
  }, [playNotificationSound]);

  const contextValue: NotificationContextType = {
    notifications,
    unreadCount: unreadCountData?.count || 0,
    isLoading,
    refreshNotifications,
    clearCache,
    testNotificationSound,
    isSoundEnabled
  };

  return (
    <NotificationContext.Provider value={contextValue}>
      {children}
    </NotificationContext.Provider>
  );
};

export const useNotificationContext = () => {
  const context = useContext(NotificationContext);
  if (context === undefined) {
    // Provide a fallback instead of throwing an error to prevent crashes
    console.warn('useNotificationContext called outside NotificationProvider, using fallback values');
    return {
      notifications: [],
      unreadCount: 0,
      isLoading: false,
      refreshNotifications: () => {},
      clearCache: () => {},
      testNotificationSound: () => {},
      isSoundEnabled: false
    };
  }
  return context;
};