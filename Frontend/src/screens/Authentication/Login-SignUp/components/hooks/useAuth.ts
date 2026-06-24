import { useState, useEffect, useCallback } from "react";
import { useSelector, useDispatch } from "react-redux";
import { useNavigate } from "react-router-dom";
import {
  selectCurrentUser,
  selectIsAuthenticated,
  logout as logoutAction,
} from "../../../../../components/redux/features/auth/authSlice";
import {
  selectUserProfile,
  selectUserInitials,
  selectUserFullName,
} from "../../../../../components/redux/features/user/userSlice";
import { useLogoutMutation } from "../../../../../components/redux/features/auth/authApi";
import { useGetUserProfileQuery } from "../../../../../components/redux/features/user/userApi";
import type {
  AuthUser,
  UserProfile,
  CompleteUser,
} from "../../../../../components/redux/features/user/types/user";
import { combineUserData } from "../../../../../components/redux/features/user/types/user";

interface UseAuthReturn {
  user: CompleteUser;
  currentUser: AuthUser | null;
  userProfile: UserProfile | null;
  isAuthenticated: boolean;
  userInitials: string;
  userFullName: string | null;

  profileImage: string | null;
  profileImageUrl: string | null;
  imageLoaded: boolean;
  imageError: boolean;

  logout: () => Promise<void>;
  handleImageError: () => void;
  refreshProfile: () => void;

  hasRole: (role: string) => boolean;
  isAdmin: boolean;
  isManager: boolean;

  isLoggingOut: boolean;
  isProfileLoading: boolean;

  logoutError: string | null;
  profileError: string | null;
}

export const useAuth = (): UseAuthReturn => {
  const dispatch = useDispatch();
  const navigate = useNavigate();

  const currentUser = useSelector(selectCurrentUser);
  const userProfile = useSelector(selectUserProfile);
  const isAuthenticated = useSelector(selectIsAuthenticated);
  const selectorUserInitials = useSelector(selectUserInitials);
  const selectorUserFullName = useSelector(selectUserFullName);
  const userInitials = selectorUserInitials || "";
  const userFullName = selectorUserFullName || null;

  const [profileImage, setProfileImage] = useState<string | null>(null);
  const [imageLoaded, setImageLoaded] = useState(false);
  const [imageError, setImageError] = useState(false);
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const [logoutError, setLogoutError] = useState<string | null>(null);

  const [logoutMutation] = useLogoutMutation();
  const {
    data: profileData,
    isLoading: isProfileLoading,
    error: profileError,
    refetch: refreshProfile,
  } = useGetUserProfileQuery(undefined, {
    skip: !isAuthenticated,
    refetchOnMountOrArgChange: true,
  });

  // Helper function to construct full image URL
  const constructImageUrl = useCallback(
    (imagePath: string | null | undefined): string | null => {
      if (!imagePath) return null;

      if (imagePath.startsWith("http://") || imagePath.startsWith("https://")) {
        return imagePath;
      }

      const baseUrl =
        import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api/";

      let cleanBaseUrl = baseUrl.endsWith("/")
        ? baseUrl.slice(0, -1)
        : baseUrl;

      if (cleanBaseUrl.endsWith("/api")) {
        cleanBaseUrl = cleanBaseUrl.slice(0, -4);
      }

      const cleanImagePath = imagePath.startsWith("/")
        ? imagePath
        : `/${imagePath}`;

      return `${cleanBaseUrl}${cleanImagePath}`;
    },
    []
  );

  const getInitials = useCallback((name: string | null | undefined): string => {
    if (!name || typeof name !== "string") return "U";

    try {
      const trimmedName = name.trim();
      if (!trimmedName) return "U";

      return trimmedName
        .split(" ")
        .filter((word) => word.length > 0)
        .map((word) => word.charAt(0).toUpperCase())
        .join("")
        .substring(0, 2);
    } catch (error) {
      console.warn("Error generating initials:", error);
      return "U";
    }
  }, []);

  useEffect(() => {
    const profilePictureUrl =
      userProfile?.profile_picture_url ||
      userProfile?.profile_picture ||
      (currentUser as any)?.profile_picture;

    if (profilePictureUrl) {
      const imageUrl = constructImageUrl(profilePictureUrl);
      setProfileImage(imageUrl);
      setImageError(false);

      // Preload the image
      if (imageUrl) {
        const img = new Image();
        img.onload = () => {
          setImageLoaded(true);
          setImageError(false);
        };
        img.onerror = () => {
          setImageLoaded(true);
          setImageError(true);
          setProfileImage(null);
        };
        img.src = imageUrl;
      }
    } else {
      setProfileImage(null);
      setImageLoaded(true);
      setImageError(false);
    }
  }, [
    userProfile?.profile_picture_url,
    userProfile?.profile_picture,
    (currentUser as any)?.profile_picture,
    constructImageUrl,
  ]);

  // Handle logout
  const logout = useCallback(async () => {
    if (isLoggingOut) return;

    setIsLoggingOut(true);
    setLogoutError(null);

    try {
      await logoutMutation().unwrap();
      dispatch(logoutAction());
      navigate("/auth", { replace: true });
    } catch (error) {
      console.error("Logout error:", error);
      setLogoutError(error instanceof Error ? error.message : "Logout failed");
      dispatch(logoutAction());
      navigate("/auth", { replace: true });
    } finally {
      setIsLoggingOut(false);
    }
  }, [logoutMutation, dispatch, navigate, isLoggingOut]);

  // Handle profile image error
  const handleImageError = useCallback(() => {
    setProfileImage(null);
    setImageError(true);
  }, []);

  const getUserName = useCallback((): string => {
    if (userFullName) return userFullName;
    if (userProfile?.full_name) return userProfile.full_name;
    if (currentUser?.name) return currentUser.name;
    if (userProfile?.first_name && userProfile?.last_name) {
      return `${userProfile.first_name} ${userProfile.last_name}`.trim();
    }
    if (currentUser?.first_name && currentUser?.last_name) {
      return `${currentUser.first_name} ${currentUser.last_name}`.trim();
    }
    if (userProfile?.first_name) return userProfile.first_name;
    if (currentUser?.first_name) return currentUser.first_name;
    if (userProfile?.email) return userProfile.email;
    if (currentUser?.email) return currentUser.email;
    return "Guest User";
  }, [userFullName, currentUser, userProfile]);

  // Create combined user data using the helper function from types
  const createCompleteUser = useCallback((): CompleteUser => {
    if (!isAuthenticated || !currentUser) {
      return {
        id: "guest",
        email: "guest@example.com",
        first_name: "Guest",
        last_name: "User",
        name: "Guest User",
        full_name: "Guest User",
        user_type: "GUEST",
        phone_number: undefined,
        is_verified: false,
        mfa_enabled: false,
        mfa_fully_configured: false,
        date_joined: new Date().toISOString(),
        last_login: null,
      };
    }

    if (userProfile) {
      return combineUserData(currentUser, userProfile);
    }

    return {
      ...currentUser,
      full_name:
        currentUser.name ||
        `${currentUser.first_name} ${currentUser.last_name}`.trim(),
      profile_picture: undefined,
      profile_picture_url: undefined,
      company: undefined,
      job_title: undefined,
      department: undefined,
      bio: undefined,
      timezone: undefined,
    };
  }, [isAuthenticated, currentUser, userProfile]);

  const user = createCompleteUser();

  const hasRole = useCallback(
    (role: string): boolean => {
      if (!user?.user_type) return false;
      return user.user_type === role;
    },
    [user?.user_type]
  );

  const isAdmin = hasRole("ADMIN");
  const isManager = hasRole("MANAGER");

  const finalUserInitials = userInitials || getInitials(getUserName());

  return {
    user,
    currentUser,
    userProfile,
    isAuthenticated,
    userInitials: finalUserInitials,
    userFullName,

    profileImage,
    profileImageUrl: profileImage,
    imageLoaded,
    imageError,

    logout,
    handleImageError,
    refreshProfile,

    hasRole,
    isAdmin,
    isManager,

    isLoggingOut,
    isProfileLoading,

    logoutError,
    profileError: profileError ? String(profileError) : null,
  };
};

// // Optional: Create a hook specifically for protected routes
// export const useAuthGuard = (requiredRole?: string) => {
//   const { isAuthenticated, hasRole, currentUser } = useAuth();
//   const navigate = useNavigate();

//   useEffect(() => {
//     if (!isAuthenticated) {
//       navigate("/login", { replace: true });
//       return;
//     }

//     if (requiredRole && !hasRole(requiredRole)) {
//       navigate("/unauthorized", { replace: true });
//       return;
//     }
//   }, [isAuthenticated, hasRole, requiredRole, navigate]);

//   return {
//     isAuthorized: isAuthenticated && (!requiredRole || hasRole(requiredRole)),
//     user: currentUser,
//   };
// };

// // Optional: Type-safe role checker hook
// export const useRoles = () => {
//   const { hasRole, currentUser } = useAuth();

//   return {
//     isAdmin: hasRole("ADMIN"),
//     isManager: hasRole("MANAGER"),
//     isUser: hasRole("USER"),
//     isGuest: hasRole("GUEST"),
//     hasAnyRole: (roles: string[]) => roles.some((role) => hasRole(role)),
//     hasAllRoles: (roles: string[]) => roles.every((role) => hasRole(role)),
//     currentRole: currentUser?.role || null,
//   };
// };
